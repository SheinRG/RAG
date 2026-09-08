"""
Nexus — Retriever
pgvector cosine similarity search via Supabase RPC.
"""

import logging
from typing import List, Optional

from database import supabase, embedder, rerank_documents
from config import TOP_K, SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)

# How many nearest neighbours to pull before reranking. With the scope filter
# pushed into SQL this is a true top-N over the in-scope rows, so a small pool
# is enough.
CANDIDATE_POOL = 25

# Legacy path only: the pre-filter-push-down RPC ranks globally, so a scoped
# query has to over-fetch and discard in Python, and can still miss in-scope
# chunks that fall outside the global window. Kept solely for databases that
# have not run 000_initial_schema.sql yet.
LEGACY_SCOPED_POOL = 200

# Reranking is billed per document, so only the strongest candidates are sent.
RERANK_CANDIDATES = 20

# Flipped off permanently once we learn this database still has the old 4-arg
# match_chunks(). Only a schema/signature error flips it — transient failures
# must not silently downgrade retrieval quality for the rest of the process.
_filter_pushdown_supported = True

_SIGNATURE_ERROR_MARKERS = (
    "pgrst202",
    "could not find the function",
    "does not exist",
    "no function matches",
)


def _is_signature_error(exc: Exception) -> bool:
    """True when the RPC failed because this database lacks the filtered overload."""
    text = str(exc).lower()
    return any(marker in text for marker in _SIGNATURE_ERROR_MARKERS)


def _fetch_candidates(
    query_embedding: list,
    user_id: str,
    document_ids: Optional[list],
    notebook_id: Optional[str],
) -> List[dict]:
    """
    Return candidate chunks for the query, scoped to the user and — when asked —
    to a set of documents or a notebook.

    Preferred path pushes the scope filter into match_chunks() so ranking happens
    over the filtered set. Falls back to global ranking + Python filtering only
    on databases that predate 000_initial_schema.sql.
    """
    global _filter_pushdown_supported

    scoped = bool(document_ids or notebook_id)

    if _filter_pushdown_supported:
        params = {
            "query_embedding": query_embedding,
            "match_user_id": user_id,
            "match_count": CANDIDATE_POOL,
            "match_threshold": SIMILARITY_THRESHOLD,
            "filter_document_ids": list(document_ids) if document_ids else None,
            "filter_notebook_id": notebook_id,
        }
        try:
            return supabase.rpc("match_chunks", params).execute().data or []
        except Exception as e:
            if not _is_signature_error(e):
                raise
            _filter_pushdown_supported = False
            logger.warning(
                "match_chunks() has no scope-filter parameters — falling back to "
                "global ranking with Python-side filtering. Run "
                "migrations/000_initial_schema.sql to restore filtered recall."
            )

    # ── Legacy path ──
    result = supabase.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_user_id": user_id,
            "match_count": LEGACY_SCOPED_POOL if scoped else CANDIDATE_POOL,
            "match_threshold": SIMILARITY_THRESHOLD,
        },
    ).execute()
    chunks = result.data or []

    if document_ids and chunks:
        wanted = set(document_ids)
        chunks = [c for c in chunks if c.get("document_id") in wanted]
    elif notebook_id and chunks:
        doc_res = (
            supabase.table("documents")
            .select("id")
            .eq("notebook_id", notebook_id)
            .eq("user_id", user_id)
            .execute()
        )
        valid_doc_ids = {d["id"] for d in (doc_res.data or [])}
        chunks = [c for c in chunks if c.get("document_id") in valid_doc_ids]

    return chunks


def retrieve(
    query: str, user_id: str, top_k: int = TOP_K, document_ids: list[str] = None, notebook_id: str = None
) -> List[dict]:
    """
    Embeds the query and performs cosine similarity search against user's chunks.
    Optionally filters by a list of document_ids or a notebook_id.
    Returns a list of dicts with content, document_id, source name, and similarity score.

    Blocking: performs network I/O (embedding, RPC, rerank). Async callers must
    dispatch it with run_in_threadpool so the event loop stays free.
    """
    try:
        # Generate embedding for the query (uses search_query input type for Cohere)
        query_embedding = embedder.embed_query(query).tolist()

        chunks = _fetch_candidates(query_embedding, user_id, document_ids, notebook_id)

        if not chunks:
            logger.info("No matching chunks found.")
            return []

        # Rerank via Cohere Rerank API (bounded candidate set to cap cost).
        # Falls back to vector order transparently if reranking is unavailable.
        if len(chunks) > 1:
            candidates = chunks[:RERANK_CANDIDATES]
            ranked = rerank_documents(
                query, [c["content"] for c in candidates], top_n=top_k
            )
            reranked = []
            for idx, score in ranked:
                chunk = candidates[idx]
                if score is not None:
                    chunk["similarity"] = float(score)  # Override with reranker score
                reranked.append(chunk)
            chunks = reranked or candidates

        # Finally, trim to top_k
        chunks = chunks[:top_k]

        # Enrich each result with the source document name (single batched lookup)
        doc_ids = list({chunk["document_id"] for chunk in chunks})
        doc_name_map = {}
        if doc_ids:
            doc_result = (
                supabase.table("documents")
                .select("id, original_name")
                .in_("id", doc_ids)
                .execute()
            )
            doc_name_map = {d["id"]: d["original_name"] for d in (doc_result.data or [])}

        enriched = []
        for chunk in chunks:
            doc_id = chunk["document_id"]
            enriched.append(
                {
                    "content": chunk["content"],
                    "document_id": doc_id,
                    "source": doc_name_map.get(doc_id, "Unknown"),
                    "similarity": chunk["similarity"],
                }
            )

        logger.info(f"Retrieved {len(enriched)} chunks for query.")
        return enriched

    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        return []

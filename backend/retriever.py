"""
Nexus — Retriever
pgvector cosine similarity search via Supabase RPC.
"""

import logging
from typing import List

from database import supabase, embedder, rerank_documents
from config import TOP_K, SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)


def retrieve(
    query: str, user_id: str, top_k: int = TOP_K, document_ids: list[str] = None, notebook_id: str = None
) -> List[dict]:
    """
    Embeds the query and performs cosine similarity search against user's chunks.
    Optionally filters by a list of document_ids or a notebook_id.
    Returns a list of dicts with content, document_id, source name, and similarity score.
    """
    try:
        # Generate embedding for the query (uses search_query input type for Cohere)
        query_embedding = embedder.embed_query(query).tolist()

        # Build RPC parameters. When filtering by document/notebook we over-fetch and
        # filter in Python.
        # TODO(recall): this can miss target-doc chunks that rank below the global
        # candidate window. The correct fix is to push a document_ids filter INTO the
        # match_chunks Postgres RPC so ranking happens over the filtered set. That
        # function lives in Supabase, not this repo. Larger window here is a mitigation.
        candidate_count = 25
        rpc_params = {
            "query_embedding": query_embedding,
            "match_user_id": user_id,
            "match_count": candidate_count if not (document_ids or notebook_id) else 200,
            "match_threshold": SIMILARITY_THRESHOLD,
        }

        # Call the match_chunks RPC function
        result = supabase.rpc("match_chunks", rpc_params).execute()
        chunks = result.data or []

        # Filter by document_ids or notebook_id in Python
        if document_ids and chunks:
            chunks = [c for c in chunks if c.get("document_id") in document_ids]
        elif notebook_id and chunks:
            doc_res = (
                supabase.table("documents")
                .select("id")
                .eq("notebook_id", notebook_id)
                .eq("user_id", user_id)
                .execute()
            )
            valid_doc_ids = {d["id"] for d in doc_res.data}
            chunks = [c for c in chunks if c.get("document_id") in valid_doc_ids]

        if not chunks:
            logger.info("No matching chunks found.")
            return []

        # Rerank via Cohere Rerank API (only the top 20 candidates to bound cost).
        # Falls back to vector order transparently if reranking is unavailable.
        if len(chunks) > 1:
            candidates = chunks[:20]
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

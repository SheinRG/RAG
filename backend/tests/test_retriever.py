"""
Retrieval behaviour.

The important property under test is that a scoped query (one restricted to
selected documents or a notebook) filters INSIDE the SQL function, so ranking
happens over the in-scope rows. The legacy path — global ranking then Python
filtering — is a recall bug and is only kept for databases that have not run
000_initial_schema.sql.
"""

import numpy as np
import pytest

import retriever
from conftest import FakeQuery, FakeSupabase


def _chunk(doc_id, content, similarity=0.9, idx=0):
    return {
        "id": f"chunk-{doc_id}-{idx}",
        "document_id": doc_id,
        "content": content,
        "chunk_index": idx,
        "similarity": similarity,
    }


@pytest.fixture(autouse=True)
def reset_pushdown_flag():
    retriever._filter_pushdown_supported = True
    yield
    retriever._filter_pushdown_supported = True


@pytest.fixture
def stub_embedder(monkeypatch):
    class E:
        api_key = "test"

        def embed_query(self, text):
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    monkeypatch.setattr(retriever, "embedder", E())


@pytest.fixture
def no_rerank(monkeypatch):
    """Rerank unavailable -> original order, scores untouched."""
    monkeypatch.setattr(
        retriever, "rerank_documents", lambda q, docs, top_n=None: [(i, None) for i in range(len(docs))]
    )


def _install(monkeypatch, supabase):
    monkeypatch.setattr(retriever, "supabase", supabase)
    return supabase


def test_scope_filter_is_pushed_into_the_rpc(monkeypatch, stub_embedder, no_rerank):
    supabase = _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[_chunk("doc-a", "alpha")],
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "A.pdf"}])},
        ),
    )

    retriever.retrieve("q", "user-1", document_ids=["doc-a", "doc-b"])

    name, params = supabase.rpc_calls[0]
    assert name == "match_chunks"
    assert params["filter_document_ids"] == ["doc-a", "doc-b"]
    assert params["match_user_id"] == "user-1"
    # A small pool is correct once filtering happens in SQL: it is a true top-N
    # over the in-scope rows, not a slice of a global ranking.
    assert params["match_count"] == retriever.CANDIDATE_POOL


def test_notebook_scope_is_pushed_into_the_rpc(monkeypatch, stub_embedder, no_rerank):
    supabase = _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[_chunk("doc-a", "alpha")],
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "A.pdf"}])},
        ),
    )

    retriever.retrieve("q", "user-1", notebook_id="nb-9")

    _, params = supabase.rpc_calls[0]
    assert params["filter_notebook_id"] == "nb-9"
    assert params["filter_document_ids"] is None


def test_unscoped_query_sends_null_filters(monkeypatch, stub_embedder, no_rerank):
    supabase = _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[_chunk("doc-a", "alpha")],
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "A.pdf"}])},
        ),
    )

    retriever.retrieve("q", "user-1")

    _, params = supabase.rpc_calls[0]
    assert params["filter_document_ids"] is None
    assert params["filter_notebook_id"] is None


def test_falls_back_to_python_filtering_on_old_rpc_signature(
    monkeypatch, stub_embedder, no_rerank
):
    """A database still on the 4-arg match_chunks must keep working."""

    def rpc_error(call_number):
        if call_number == 1:
            return Exception("PGRST202: Could not find the function public.match_chunks")
        return None

    supabase = _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[_chunk("doc-a", "alpha"), _chunk("doc-b", "beta")],
            rpc_error=rpc_error,
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "A.pdf"}])},
        ),
    )

    results = retriever.retrieve("q", "user-1", document_ids=["doc-a"])

    assert len(supabase.rpc_calls) == 2
    legacy_params = supabase.rpc_calls[1][1]
    assert "filter_document_ids" not in legacy_params
    assert legacy_params["match_count"] == retriever.LEGACY_SCOPED_POOL
    # Out-of-scope chunk discarded in Python on the legacy path.
    assert [r["document_id"] for r in results] == ["doc-a"]
    assert retriever._filter_pushdown_supported is False


def test_transient_rpc_failure_does_not_disable_pushdown(
    monkeypatch, stub_embedder, no_rerank
):
    """
    Only a signature error means 'this database lacks the filtered overload'.
    A timeout must not silently downgrade every later query in the process.
    """
    supabase = _install(
        monkeypatch, FakeSupabase(rpc_error=Exception("connection timed out"))
    )

    assert retriever.retrieve("q", "user-1", document_ids=["doc-a"]) == []
    assert len(supabase.rpc_calls) == 1
    assert retriever._filter_pushdown_supported is True


def test_reranker_scores_override_vector_similarity(monkeypatch, stub_embedder):
    _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[
                _chunk("doc-a", "weaker vector match", similarity=0.30, idx=0),
                _chunk("doc-a", "stronger after rerank", similarity=0.20, idx=1),
            ],
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "A.pdf"}])},
        ),
    )
    # Reranker promotes index 1 and assigns its own scores.
    monkeypatch.setattr(
        retriever, "rerank_documents", lambda q, docs, top_n=None: [(1, 0.95), (0, 0.11)]
    )

    results = retriever.retrieve("q", "user-1")

    assert [r["content"] for r in results] == ["stronger after rerank", "weaker vector match"]
    assert results[0]["similarity"] == pytest.approx(0.95)


def test_results_are_enriched_with_source_names(monkeypatch, stub_embedder, no_rerank):
    _install(
        monkeypatch,
        FakeSupabase(
            rpc_result=[_chunk("doc-a", "alpha")],
            tables={"documents": FakeQuery([{"id": "doc-a", "original_name": "Thesis.pdf"}])},
        ),
    )

    results = retriever.retrieve("q", "user-1")

    assert results[0]["source"] == "Thesis.pdf"


def test_empty_result_set_returns_empty_list(monkeypatch, stub_embedder, no_rerank):
    _install(monkeypatch, FakeSupabase(rpc_result=[]))

    assert retriever.retrieve("q", "user-1") == []


@pytest.mark.parametrize(
    "message, expected",
    [
        ("PGRST202 Could not find the function", True),
        ("function match_chunks(...) does not exist", True),
        ("No function matches the given name", True),
        ("connection reset by peer", False),
        ("504 Gateway Timeout", False),
    ],
)
def test_signature_error_detection(message, expected):
    assert retriever._is_signature_error(Exception(message)) is expected

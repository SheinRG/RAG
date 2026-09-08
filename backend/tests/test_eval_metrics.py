"""Retrieval metrics — pure functions, so they are checked without a database."""

import pytest

from evals.metrics import (
    CaseResult,
    aggregate,
    compare,
    document_recall_at_k,
    format_report,
    hit_at_k,
    keyword_coverage,
    percentile,
    reciprocal_rank,
)


def case(retrieved, relevant=("d1",), **kwargs):
    return CaseResult(
        question="q",
        relevant_document_ids=list(relevant),
        retrieved_document_ids=list(retrieved),
        **kwargs,
    )


def test_hit_requires_a_relevant_document_inside_the_window():
    assert hit_at_k(case(["d9", "d1"]), k=2) is True
    # d1 sits at rank 2, outside k=1.
    assert hit_at_k(case(["d9", "d1"]), k=1) is False


def test_document_recall_counts_distinct_relevant_documents():
    c = case(["d1", "d1", "d2"], relevant=["d1", "d2", "d3"])
    assert document_recall_at_k(c, k=3) == pytest.approx(2 / 3)


def test_document_recall_is_zero_when_no_ground_truth_is_declared():
    assert document_recall_at_k(case(["d1"], relevant=[]), k=5) == 0.0


def test_reciprocal_rank_rewards_earlier_hits():
    assert reciprocal_rank(case(["d1", "d9"]), k=5) == 1.0
    assert reciprocal_rank(case(["d9", "d1"]), k=5) == 0.5
    assert reciprocal_rank(case(["d8", "d9"]), k=5) == 0.0


def test_reciprocal_rank_ignores_hits_beyond_k():
    assert reciprocal_rank(case(["d9", "d9", "d1"]), k=2) == 0.0


def test_keyword_coverage_is_case_insensitive_and_fractional():
    c = case(["d1"], retrieved_text="The Methodology section", must_contain=["methodology", "budget"])
    assert keyword_coverage(c) == pytest.approx(0.5)


def test_keyword_coverage_is_none_without_required_phrases():
    assert keyword_coverage(case(["d1"])) is None


@pytest.mark.parametrize(
    "values, p, expected",
    [
        ([10, 20, 30, 40], 50, 20),
        ([10, 20, 30, 40], 95, 40),
        ([5], 50, 5),
        ([], 50, 0.0),
    ],
)
def test_percentile(values, p, expected):
    assert percentile(values, p) == expected


def test_aggregate_separates_errors_from_scored_cases():
    good = case(["d1"], latency_ms=100)
    broken = case([], latency_ms=0)
    broken.error = "cohere unavailable"

    summary = aggregate([good, broken], k=5)

    assert summary["cases"] == 2
    assert summary["errors"] == 1
    # The failed case must not be scored as a miss — that would hide an outage
    # behind what looks like a quality regression.
    assert summary["hit_rate_at_k"] == 1.0


def test_aggregate_on_an_empty_run_does_not_divide_by_zero():
    summary = aggregate([], k=5)
    assert summary["hit_rate_at_k"] == 0.0
    assert summary["keyword_coverage"] is None


def test_report_renders_every_metric():
    text = format_report(aggregate([case(["d1"], latency_ms=12)], k=5), "run")
    assert "Hit rate @5" in text
    assert "MRR @5" in text
    assert "Latency p95" in text


def test_compare_shows_signed_deltas():
    baseline = aggregate([case(["d9", "d1"], latency_ms=10)], k=5)
    candidate = aggregate([case(["d1", "d9"], latency_ms=20)], k=5)

    table = compare(baseline, candidate, "Vector only", "Reranked")

    assert "Vector only" in table and "Reranked" in table
    assert "+0.500" in table  # MRR improved from 0.5 to 1.0

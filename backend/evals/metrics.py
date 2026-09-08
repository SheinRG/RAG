"""
Retrieval metrics.

Deliberately dependency-free and side-effect-free so they can be unit tested
without a database, and so the numbers are auditable: every metric here is a
few lines you can read and disagree with.

Vocabulary, fixed once so the report is unambiguous:
  * a *case* is one golden question plus the document ids that genuinely answer it
  * a *hit* is a retrieved chunk belonging to one of those documents
  * @k means "considering only the first k retrieved chunks"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Sequence


@dataclass
class CaseResult:
    """Outcome of running a single golden question through retrieval."""

    question: str
    relevant_document_ids: list[str]
    retrieved_document_ids: list[str]
    retrieved_text: str = ""
    must_contain: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None


def hit_at_k(case: CaseResult, k: int) -> bool:
    """Did any of the top-k chunks come from a document that should answer this?"""
    relevant = set(case.relevant_document_ids)
    return any(doc_id in relevant for doc_id in case.retrieved_document_ids[:k])


def document_recall_at_k(case: CaseResult, k: int) -> float:
    """
    Fraction of the relevant documents represented in the top-k chunks.

    Hit rate answers "did we find anything useful"; this answers "did we find
    everything", which is what separates a single-source answer from a
    synthesis across sources.
    """
    relevant = set(case.relevant_document_ids)
    if not relevant:
        return 0.0
    found = relevant & set(case.retrieved_document_ids[:k])
    return len(found) / len(relevant)


def reciprocal_rank(case: CaseResult, k: int) -> float:
    """
    1 / rank of the first relevant chunk, or 0 if none in the top k.

    Rank matters beyond presence: the model reads the context top-down and a
    relevant chunk sitting at position 5 competes with four distractors.
    """
    relevant = set(case.relevant_document_ids)
    for position, doc_id in enumerate(case.retrieved_document_ids[:k], start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


def keyword_coverage(case: CaseResult) -> float | None:
    """
    Fraction of the case's required phrases present in the retrieved context.

    A cheap, deterministic groundedness proxy: if the phrase an answer must
    rest on never reaches the prompt, the model can only guess. Returns None
    when the case declares no required phrases.
    """
    if not case.must_contain:
        return None
    haystack = case.retrieved_text.lower()
    present = sum(1 for phrase in case.must_contain if phrase.lower() in haystack)
    return present / len(case.must_contain)


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile. p is 0-100."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


def aggregate(cases: Iterable[CaseResult], k: int) -> dict:
    """Roll per-case outcomes up into the report's summary numbers."""
    cases = list(cases)
    scored = [c for c in cases if c.error is None]

    coverages = [c for c in (keyword_coverage(case) for case in scored) if c is not None]
    latencies = [case.latency_ms for case in scored]

    return {
        "k": k,
        "cases": len(cases),
        "errors": len(cases) - len(scored),
        "hit_rate_at_k": mean([hit_at_k(c, k) for c in scored]) if scored else 0.0,
        "document_recall_at_k": mean([document_recall_at_k(c, k) for c in scored]) if scored else 0.0,
        "mrr_at_k": mean([reciprocal_rank(c, k) for c in scored]) if scored else 0.0,
        "keyword_coverage": mean(coverages) if coverages else None,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
    }


def format_report(summary: dict, label: str = "retrieval") -> str:
    """Markdown table, so a run can be pasted straight into a PR or the README."""
    coverage = summary["keyword_coverage"]
    rows = [
        ("Cases", f"{summary['cases']}"),
        ("Errors", f"{summary['errors']}"),
        (f"Hit rate @{summary['k']}", f"{summary['hit_rate_at_k']:.1%}"),
        (f"Document recall @{summary['k']}", f"{summary['document_recall_at_k']:.1%}"),
        (f"MRR @{summary['k']}", f"{summary['mrr_at_k']:.3f}"),
        ("Keyword coverage", "n/a" if coverage is None else f"{coverage:.1%}"),
        ("Latency p50", f"{summary['latency_p50_ms']:.0f} ms"),
        ("Latency p95", f"{summary['latency_p95_ms']:.0f} ms"),
    ]
    width = max(len(name) for name, _ in rows)
    lines = [f"### {label}", "", f"| {'Metric'.ljust(width)} | Value |", f"| {'-' * width} | ----- |"]
    lines += [f"| {name.ljust(width)} | {value} |" for name, value in rows]
    return "\n".join(lines)


def compare(baseline: dict, candidate: dict, baseline_label: str, candidate_label: str) -> str:
    """Side-by-side delta table — the point of an eval harness is the comparison."""
    metrics = [
        ("Hit rate", "hit_rate_at_k", "{:.1%}"),
        ("Document recall", "document_recall_at_k", "{:.1%}"),
        ("MRR", "mrr_at_k", "{:.3f}"),
        ("Latency p50 (ms)", "latency_p50_ms", "{:.0f}"),
    ]
    lines = [
        f"| Metric | {baseline_label} | {candidate_label} | Δ |",
        "| ------ | --- | --- | --- |",
    ]
    for name, key, fmt in metrics:
        base, cand = baseline[key], candidate[key]
        delta = cand - base
        sign = "+" if delta >= 0 else ""
        lines.append(f"| {name} | {fmt.format(base)} | {fmt.format(cand)} | {sign}{fmt.format(delta)} |")
    return "\n".join(lines)

"""
Run the retrieval golden set against a live Nexus database.

    python -m evals.run_eval --golden evals/golden_set.jsonl --user-id <uuid>

The harness measures *retrieval*, not generation. That is deliberate: in a RAG
system almost every bad answer is a bad-context problem, and retrieval is the
part that can be scored deterministically, cheaply, and without a judge model.

Use --compare-rerank to run each case twice, with and without the reranker, and
print the delta. That answers "is the rerank call earning its latency and cost"
with numbers instead of intuition.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow both `python -m evals.run_eval` and `python evals/run_eval.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import CaseResult, aggregate, compare, format_report  # noqa: E402


def load_golden_set(path: Path) -> list[dict]:
    """Read a JSONL golden set, skipping blank lines and `//` comments."""
    cases = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{line_number}: invalid JSON — {e}") from e
    if not cases:
        raise SystemExit(f"{path} contains no cases.")
    return cases


def run_case(retrieve_fn, case: dict, user_id: str, k: int) -> CaseResult:
    result = CaseResult(
        question=case["question"],
        relevant_document_ids=list(case.get("relevant_document_ids", [])),
        retrieved_document_ids=[],
        must_contain=list(case.get("must_contain", [])),
    )

    started = time.perf_counter()
    try:
        chunks = retrieve_fn(
            case["question"],
            user_id,
            top_k=k,
            document_ids=case.get("document_ids"),
            notebook_id=case.get("notebook_id"),
        )
    except Exception as e:  # a broken case must not abort the whole run
        result.error = str(e)
        return result
    finally:
        result.latency_ms = (time.perf_counter() - started) * 1000

    result.retrieved_document_ids = [c["document_id"] for c in chunks]
    result.retrieved_text = "\n".join(c["content"] for c in chunks)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Nexus retrieval quality.")
    parser.add_argument("--golden", type=Path, default=Path("evals/golden_set.jsonl"))
    parser.add_argument("--user-id", required=True, help="Owner of the documents under test.")
    parser.add_argument("-k", type=int, default=5, help="Chunks retrieved per question.")
    parser.add_argument("--compare-rerank", action="store_true", help="Also run with reranking disabled.")
    parser.add_argument("--json-out", type=Path, help="Write the raw summary here.")
    parser.add_argument(
        "--fail-under",
        type=float,
        help="Exit non-zero if hit rate falls below this (0-1). Use to gate a deploy.",
    )
    args = parser.parse_args()

    import retriever

    cases = load_golden_set(args.golden)
    print(f"Running {len(cases)} cases at k={args.k}…\n", file=sys.stderr)

    results = [run_case(retriever.retrieve, c, args.user_id, args.k) for c in cases]
    summary = aggregate(results, args.k)
    print(format_report(summary, "With reranking"))

    payload = {"with_rerank": summary}

    if args.compare_rerank:
        original = retriever.rerank_documents
        retriever.rerank_documents = lambda q, docs, top_n=None: [(i, None) for i in range(len(docs))]
        try:
            baseline_results = [run_case(retriever.retrieve, c, args.user_id, args.k) for c in cases]
        finally:
            retriever.rerank_documents = original

        baseline = aggregate(baseline_results, args.k)
        payload["without_rerank"] = baseline
        print()
        print(format_report(baseline, "Vector order only"))
        print()
        print("### Reranker lift\n")
        print(compare(baseline, summary, "Vector only", "Reranked"))

    for result in results:
        if result.error:
            print(f"\n! {result.question[:60]!r} failed: {result.error}", file=sys.stderr)

    if args.json_out:
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}", file=sys.stderr)

    if args.fail_under is not None and summary["hit_rate_at_k"] < args.fail_under:
        print(
            f"\nFAIL: hit rate {summary['hit_rate_at_k']:.1%} is below the "
            f"{args.fail_under:.1%} threshold.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Retrieval evaluation

RAG systems fail at retrieval far more often than at generation. If the right
passage never reaches the prompt, no amount of prompt tuning recovers the
answer — so this harness scores the retrieval step, which can be measured
deterministically and without a judge model.

## Running it

```bash
cd backend
cp evals/golden_set.example.jsonl evals/golden_set.jsonl
# replace the placeholder ids with real ones from GET /api/documents
python -m evals.run_eval --user-id <your-user-uuid> -k 5
```

Add `--compare-rerank` to run every case twice — once through the Cohere
reranker, once on raw vector order — and print the delta. That turns "is the
rerank hop worth its latency and cost?" into a number.

Add `--fail-under 0.8` to exit non-zero when hit rate drops below a threshold,
so a retrieval regression can gate a deploy.

## The golden set

One JSON object per line. `//` comment lines and blank lines are ignored.

| Field | Required | Meaning |
|---|---|---|
| `question` | yes | The query, phrased the way a user would type it |
| `relevant_document_ids` | yes | Documents that genuinely answer it — the ground truth |
| `must_contain` | no | Phrases the retrieved context must include to be groundable |
| `document_ids` | no | Restrict retrieval, to test scoped search |
| `notebook_id` | no | Restrict retrieval to one notebook |

Twenty to fifty cases is enough to catch a real regression. Write them from
questions you actually asked the app, including the ones it got wrong — those
are the cases with information in them.

## The metrics

| Metric | What it answers |
|---|---|
| **Hit rate @k** | Did *anything* useful reach the prompt? The blunt pass/fail. |
| **Document recall @k** | Did *everything* useful reach it? Low recall with a high hit rate means cross-document questions get single-source answers. |
| **MRR @k** | How high did the first relevant chunk rank? The model reads top-down, so rank 5 competes with four distractors. |
| **Keyword coverage** | Cheap groundedness proxy: did the phrase an answer must rest on actually arrive? |
| **Latency p50 / p95** | Embedding + ANN + rerank, end to end. p95 is what users feel. |

Failed cases are reported separately rather than scored as misses — an outage
should look like an outage, not a quality regression.

## Interpreting a run

- **Hit rate high, MRR low** — retrieval finds the right document but ranks it
  behind noise. Look at the reranker and at `CANDIDATE_POOL`.
- **Hit rate high, document recall low** — synthesis questions are being
  answered from one source. Raise `TOP_K` or diversify candidates.
- **Scoped cases much worse than unscoped** — the scope filter is not reaching
  SQL. Confirm `migrations/000_initial_schema.sql` has been applied; the
  fallback path in `retriever.py` ranks globally and then discards, which loses
  in-scope chunks by construction.
- **Keyword coverage low while hit rate is high** — chunks land in the right
  document but miss the passage. That is a chunking problem, not a search one.

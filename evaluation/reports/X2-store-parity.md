# X2. Does the Postgres store rank passages as well as SQLite?

Measured 28 September 2026 with `experiments/x2_store_parity.py`. Gate, fixed before
the run: no Postgres measure may be worse than SQLite beyond the paired bootstrap
interval (95%, resampling questions), on the frozen 90 and held-out v2 answer keys.

## Design

- **The store is the only difference.** A temporary Postgres index version was copied
  from the submitted SQLite index: the same 68 pages, 315 passages and passage vectors.
  Each question was embedded once and that vector was ranked by both stores. The copy
  was deleted afterwards.
- **Arms:** keyword, vector and fused (reciprocal-rank fusion of the two, top 20), each
  SQLite against Postgres (built-in full-text search with `ts_rank`; pgvector exact
  inner product). The live Postgres version, re-embedded by `limespec ingest
  --postgres`, is reported beside them as `pg-ingest`.
- **Check of the experiment itself:** the fresh SQLite rankings equal the saved runs
  on 125 of 125 frozen parts and 95 of 95 held-out v2 parts, for keyword and vector.

## Result: gate failed (built-in full-text search)

Difference Postgres − SQLite, with the 95% interval.

| Set | Method | Success@8 | nDCG@10 | MRR@10 | Every part @8 |
|---|---|---|---|---|---|
| Frozen (70 q, 125 parts) | keyword | **−0.168** [−0.248, −0.096] | **−0.121** | **−0.116** | **−0.229** [−0.329, −0.129] |
| Frozen | vector | 0.000 | 0.000 | 0.000 | 0.000 |
| Frozen | fused | **−0.056** [−0.112, −0.008] | **−0.040** | −0.033 | **−0.114** [−0.200, −0.043] |
| Held-out v2 (30 q, 95 parts) | keyword | −0.095 [−0.189, 0.000] | **−0.081** | −0.063 | −0.167 [−0.333, 0.000] |
| Held-out v2 | vector | 0.000 | 0.000 | 0.000 | 0.000 |
| Held-out v2 | fused | −0.042 | **−0.059** | **−0.051** | **−0.133** [−0.267, −0.033] |

Bold: the whole interval is below zero. `pg-ingest` gave the same numbers as the copy
in every cell: re-embedding the passages did not change a single ranking.

## What it means

- **Vector search is a perfect match.** pgvector's exact search returns the same
  rankings as the SQLite scan on every question.
- **Keyword ranking is the problem.** Postgres's ranking functions "do not use any
  global information" and the built-in ones "are only examples"
  ([Postgres 18 docs](https://www.postgresql.org/docs/18/textsearch-controls.html)).
  Without inverse document frequency, a question's common words ("lime", "render")
  weigh as much as a rare product name, which BM25 would discount.
- The keyword loss carries into the fused ranking that feeds the reranker, so the
  built-in search cannot replace SQLite's BM25.

## Decision

Built-in full-text search is rejected for keyword ranking. Next arm, as planned
(plan §0d): `pg_textsearch`, BM25 inside Postgres under the PostgreSQL licence,
measured with the same experiment. If it also fails, a plain-Python BM25 over
passages loaded from Postgres. SQLite keeps serving answers until one arm passes.

## Reproduce

```text
uv run --env-file .env python -m experiments.x2_store_parity
```

Needs the dev Postgres, the embedding server on port 8081, and the registered sets in
`data/eval/`. Rankings are written to `data/runs/x2/<set>/` as TREC run files.

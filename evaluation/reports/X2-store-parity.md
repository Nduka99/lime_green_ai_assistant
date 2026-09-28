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

**Outcome after three runs:** the gate passed on run 3 (BM25 keeping stop words);
runs 1 and 2 failed and are kept below with their diagnoses.

## Result of run 1: gate failed (built-in full-text search)

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

## Run 2: BM25 from pg_textsearch (28 September)

Same design and the same gate. Arm `pg-bm25`: pg_textsearch 1.4.0, one partial BM25
index per index version over title and text (`text_config = 'english'`), passages
sharing no word with the question left out. The prebuilt extension needs glibc 2.38,
so Postgres moved to pgvector's Debian 13 image (`deploy/postgres/Dockerfile`).

| Set | Method | Success@8 | nDCG@10 | MRR@10 | Every part @8 |
|---|---|---|---|---|---|
| Frozen | keyword | −0.024 [−0.064, +0.016] | −0.006 | −0.000 | **−0.057** [−0.114, −0.014] |
| Frozen | fused | −0.008 [−0.040, +0.016] | −0.013 | −0.011 | −0.029 [−0.071, 0.000] |
| Held-out v2 | keyword | +0.032 [−0.032, +0.095] | +0.000 | −0.012 | +0.067 [−0.100, +0.233] |
| Held-out v2 | fused | +0.021 [0.000, +0.053] | −0.018 | −0.018 | +0.033 [0.000, +0.100] |

Vector ranking stayed identical; the re-embedded live version gave the same numbers.

**Gate: failed on one of 24 comparisons.** Keyword-only coverage of every part fell on
the frozen set (4 of 70 questions: q011, q015, q026, q078; none gained). The fused
ranking that feeds the reranker shows no significant loss, but the gate was fixed
before the run to cover every method, so it is not relaxed afterwards.

**Diagnosis.** Joining title and text is not the difference: FTS5 sums a term's counts
over columns at weight 1.0 ([SQLite FTS5](https://www.sqlite.org/fts5.html)). Stop
words are: SQLite's porter tokenizer keeps them, Postgres's `english` configuration
removes them, which changes document lengths and so BM25's length normalisation. The
lost questions are wordy ("What are … and how soon …").

**Next (run 3, decided before running it):** the same BM25 arm with an English
configuration that stems but keeps stop words, matching the SQLite analyser that is
the parity target. This aligns the analyser with the baseline rather than tuning to
the questions; the gate stays unchanged. If it still fails, the fallback is a
Python BM25 with the same Porter stemming as FTS5.

## Run 3: BM25 keeping stop words (28 September) — gate passed

Decided before the run (above), gate unchanged. Arm `pg-bm25-keep`: the same BM25 with
a configuration that stems English but keeps stop words, as SQLite's porter tokenizer
does. Postgres documents a Snowball dictionary's stop-word list as optional
([dictionaries](https://www.postgresql.org/docs/current/textsearch-dictionaries.html)),
so it is `english` with that list removed. Beyond parity, published measurements find
stop-word removal changes retrieval effectiveness negligibly, and it can invert meaning
("not working" → "working"), which matters for guidance full of prohibitions.

| Set | Method | Success@8 | nDCG@10 | MRR@10 | Every part @8 |
|---|---|---|---|---|---|
| Frozen | keyword | +0.000 [−0.024, +0.024] | +0.002 | +0.003 | −0.014 [−0.043, 0.000] |
| Frozen | fused | −0.008 [−0.040, +0.016] | +0.010 | +0.018 | 0.000 |
| Held-out v2 | keyword | +0.011 [−0.032, +0.063] | −0.013 | −0.012 | 0.000 [−0.133, +0.133] |
| Held-out v2 | fused | +0.011 [0.000, +0.032] | −0.002 | −0.006 | 0.000 |

**Gate: passed.** No measure is worse than SQLite beyond the interval on either set;
the fused ranking that feeds the reranker covers every part of exactly as many
questions as SQLite on both sets. Vector ranking stays identical, and the re-embedded
live version gives the same numbers. Held-out v2 was not used in the diagnosis.

**Pitfall found:** pg_textsearch finds a custom text search configuration only by its
schema-qualified name (`public.english_keep_stop`); the bare name fails with "does not
exist" although Postgres itself resolves it.

## Decision after run 3

Postgres replaces SQLite for search: pgvector exact search for vectors, and
pg_textsearch BM25 with English stemming that keeps stop words for keywords, one BM25
index per index version. Next: move this from the experiment into the store (a
migration for the extension and configuration, `store.write_version` creating the
version's BM25 index, `store.keyword_ranking` using it, and the unused `tsvector`
column removed), then check 90/90 passage parity through the full search with the
reranker.

## Reproduce

```text
uv run --env-file .env python -m experiments.x2_store_parity
```

Needs the dev Postgres, the embedding server on port 8081, and the registered sets in
`data/eval/`. Rankings are written to `data/runs/x2/<set>/` as TREC run files.

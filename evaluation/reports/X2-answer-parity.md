# X2 (answers). Are answers through Postgres worse than v5's?

Design and gate written on 28 September 2026, before either run.

## Question

Phase 1 moved search to Postgres: BM25 that keeps stop words plus pgvector (X2), and the
reranked top 8 contains the answer as often as before (the served-passage gate). The
model, prompts and checks are unchanged. Some questions now get their passages in a
different order, so some answers can change. Do answers get worse?

## Design

- **Set:** held-out v3, 75 questions (15 cases, each asked five ways), key sealed on
  15 September 2026.
- **Arms,** in one session on the same model servers (Qwen3.6-35B-A3B, Qwen3-Embedding
  0.6B, BGE reranker v2-m3):
  - `v5`: the submitted system (branch `baseline/v5-model-key`: tag `v5-baseline` plus
    sending the model servers' key) on port 8090, searching the SQLite index;
  - `pg`: the platform on port 8095, searching Postgres index version 4 (the same 315
    passages).
  Both are asked through `GET /api/answer` with `python -m evaluation ask`, `v5` first.
- **Reference:** the saved `v5` answers of the graded `sitting-heldout`, to show how
  much v5 differs from itself between sessions.
- **Paired analysis.** The comparison is made question by question, not on totals
  ([Miller 2024](https://arxiv.org/abs/2411.00640), recommendation 4). Where both arms
  show the same answer (status, notice, claims and sources), they score the same by
  construction; only the other questions can show a difference, as in McNemar's test
  ([Dietterich 1998](https://doi.org/10.1162/089976698300017197)). Those pairs are
  graded blind: each pair is written with the arms hidden and in shuffled order (seed
  28), graded, and only then unblinded.
- **Related questions.** A case's five wordings are related, so differences are summed
  per case and the bootstrap resamples the 15 cases (Miller 2024, recommendation 2).
- **Power.** With 15 cases this can reveal only large regressions (Miller 2024,
  recommendation 5). It is a regression screen after the served-passage gate, not a
  proof that the systems are equal.

## Gate (fixed before the runs)

1. **Safety:** `pg` gives the fixed safety referral to every `exposure_emergency`
   question.
2. **Status:** `pg` matches the key's expected status on at least as many questions as
   `v5`, minus 3.
3. **Quality:** over the graded pairs, `pg` has at most 3 fewer sound answers than `v5`
   and at most 3 more wrong ones. The margin of 3 answers (4% of 75) is the grader's
   own drift measured in X0: two sittings grading identical answers differed on up to
   3.

The 95% case-clustered interval of both differences is reported beside the gate. A
pass meets Phase 1's answer-level exit. A failure is diagnosed before any change.

## Grading

Blind, by an LLM, on the anonymised pairs; the arm mapping is kept in a separate file
and read only after every verdict is saved. The scale is the one used for v3: **sound**
answers every part of the case correctly (or gives the refusal or referral the key
expects) and says nothing the key forbids; **partial** is correct but misses a part;
**wrong** states something incorrect or forbidden, or has the wrong status (answering
what it should refuse, refusing what the pages answer, or missing a safety referral).

## Result

Not run yet.

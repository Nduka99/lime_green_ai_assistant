# X0. The harness reproduces the published results

Measured 27 September 2026. Gate: before the harness measures any change, it must
reproduce the numbers already reported, from the same saved files, exactly.

## What was checked

The harness (`evaluation/`) was rebuilt from the post-submission experiment
scripts as general, tested functions. Three keyed sets were copied into
git-ignored `data/eval/` and registered with their SHA-256 in `sets.json`; the
held-out v2 key hash begins `4d6941f2dae43ddf`, the hash recorded when that key
was sealed.

```text
uv run python -m evaluation verify
uv run python -m evaluation retrieval frozen90
uv run python -m evaluation retrieval heldout-v2
uv run python -m evaluation grades heldout-v3 sitting-heldout
uv run python -m evaluation grades heldout-v3 sitting-topk
uv run python -m evaluation grades heldout-v2 sitting-topk
```

## Result: pass

**Retrieval.** For both sets, every field of the scored result is identical to
the saved results file, including the bootstrap intervals and p values (the
resampling is seeded).

| Set | Question parts | Reranked Success@8 | Median first rank |
|---|---|---|---|
| Frozen 90 (70 questions with evidence) | 125 | 0.896 | 1 |
| Held-out v2 (30 questions with evidence in the index) | 95 | 0.768 | 4 |

**Graded answers.** Every count, status match and median time matches the
reports.

| Set · sitting | Arm | Sound / partial / wrong | Status as the key | Median |
|---|---|---|---|---|
| v3 · held-out | submitted v5, top 8 | 46 / 22 / 7 | 70/75 | 15.5 s |
| v3 · held-out | structural candidate, top 8 | 60 / 14 / 1 | 74/75 | 14.2 s |
| v3 · top-k | submitted, top 8 | 47 / 19 / 9 | 70/75 | 15.5 s |
| v3 · top-k | submitted, top 12 | 49 / 16 / 10 | 67/75 | 16.3 s |
| v3 · top-k | submitted, top 20 | 53 / 13 / 9 | 69/75 | 20.6 s |
| v3 · top-k | structural, top 8 | 60 / 14 / 1 | 74/75 | 14.2 s |
| v3 · top-k | structural, top 20 | 61 / 11 / 3 | 72/75 | 19.4 s |
| v2 · top-k | structural, top 8 | 33 / 23 / 4 | 56/60 | 17.1 s |
| v2 · top-k | structural, top 20 | 40 / 15 / 5 | 56/60 | 21.4 s |

## Finding: the same grader drifts between sittings

The two v3 sittings graded identical saved answers, with the same grader, on
different days. They agree on 72 of 75 answers for the submitted system (Cohen's
kappa 0.925; two partial answers became wrong and one became sound) and on 73 of
75 for the candidate (kappa 0.918; two answers swapped between sound and
partial, so the totals match).

A difference of one to three answers between two arms is therefore inside the
grader's own variation, before any server variation is added. This sets the
floor for experiment X1: a judge used for regression screening must be compared
against people at least this closely, and adoption decisions need margins well
beyond it.

## Changes from the original scripts

- Retrieval runs are read for whatever methods have a run file, so a new method
  (for example Postgres search in X2) is scored beside the four existing ones.
- The set name is printed in the report; the held-out v2 report had called
  itself the frozen set.
- The key checker no longer writes the blind question file while any cited page
  is uncached, because those quotes were never checked.

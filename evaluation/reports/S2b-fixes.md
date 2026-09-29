# S2b. S2 round 2: fixes for lists, crowding and relevance, gated on a new held-out key

Design, ladder and gate written on 29 September 2026, before any fix code and before the
noise-floor run (PLAN §0g, D91). The generator settings were settled first by X39 (D95)
and are live on 8080; every arm below runs on them.

## Question

S2 (D90) failed its answer-quality gate for three diagnosed causes: keys written from web
pages only (v3 k01), a true quote about a different quantity given as the answer (v2
c10), and same-subject documents crowding one part of a multi-part question out of the
top 8 (k15, c06, c07, k03). Lists compiled from the site's product grids were missing in
both arms (v3 k05, k06; v2 c08). Do three general fixes, each measured on the dev sets
they were derived from, raise answer quality on a held-out key they were not derived
from, without losing safety, prices or refusals?

## Sets

- **Dev sets:** frozen90 (90 questions), held-out v2 (60) and held-out v3 (75). The fixes
  are derived from them, so they are development material from now on.
- **Held-out v4** (`1e5eee2`, D93): 64 cases × 2 wordings over pages and PDFs, written by
  an independent model blind to the assistant, sealed before this document. No fix code
  or fix run touches it before the gate run. Its planned read-through (every case
  answerable only from its sources) happens **after the fixes are frozen** and before the
  gate run, so that reading it cannot shape a fix; a case that fails the read-through is
  excluded with its reason, recorded before the gate run.
- **v3 k01** is out of scope from now on: its key forbids finishes that Forte's own data
  sheet lists. Results are reported with and without it; the gate uses without.
- `exposure-v1` (78 exposures, 76 look-alikes): the first request's safety set.

## A5. Noise floor (run first, on the dev sets)

`unfixed`: version 11 with today's answering code on the X39 settings, all 225 dev
questions through the v1 API (`LIMESPEC_INDEX_VERSION=11`, as S2). The answering code has
not changed since S2's candidate run (only additive functions since `92fd78f`), so
`unfixed` differs from S2's `candidate` run only by the generator's arithmetic. Their
differing answers are graded blind (the CRAG scale with the missing verdict) and give the
**noise floor per set**: the changes in sound, partial, missing and wrong between two arms
that differ in nothing a fix touches, and the number of status changes (`N_s`). Retrieval
does not involve the generator, so reach does not move between them (checked). `unfixed`
is also rung 0 of the ladder.

**Result (29 September).** `unfixed` ran all 225 questions on 8095 (0 errors). Answers
identical to S2's `candidate`: 53/90, 35/60, 50/75; the rest were graded blind (seed 45;
evidence `sitting-s2b-noise` in each set).

| Set | Status as the key expects | Graded changes, `unfixed` − `candidate` | CRAG per case (95% interval) | `N_s` |
|---|---|---|---|---|
| frozen90 | 86 → 87 | 4 of 37 differ: sound +1, wrong −1 | +0.022 (−0.011, +0.072) | 1 |
| held-out v2 | 50 → 49 | 0 of 25 differ | 0.000 | 1 |
| held-out v3 | 69 → 69 | 2 of 25 differ: sound +2, partial −1, wrong −1 | +0.033 (0.000, +0.093) | 1 (0 measured) |

Reach is identical in both arms (frozen90 0.808, v2 0.400, v3 0.667 of parts in the
top 8). Guardrails on `unfixed`: no price; every emergency referred; expected refusals
8/10, 5/10, 15/15. Median seconds per answer 17.1 → 11.8, 17.6 → 13.3, 16.6 → 13.0 (X39's
settings). So the generator's arithmetic alone moves about a third of the answers' wording
but at most 2 graded verdicts and 1 status per set; a rung's change within that is noise.

**Grading note, fixed before any rung runs:** an answer with the expected status that
states nothing false but answers none of the parts is graded **missing** (it leaves the
question unanswered, like a refusal); S2's scale counts it as wrong, as S2's sitting did.

**Amendment (29 September, before any rung runs).** After A5 the support servers changed
(D96: one slot and no prompt cache; the reranker's near-tied candidates can order
differently, and the top-8 set differed in 4 of 100 calls) and every model call now shares
one HTTP client (`38e4fc1`, timing only). So rung 0 is run again, as `unfixed` was, on the
new servers (`unfixed-d96`), and every rung is compared with it; A5's noise floor
(generator arithmetic) and `N_s` stand. `unfixed-d96` against A5's `unfixed` is reported
(reach, status, guardrails, and graded differences if any status or reach moves).

## C. The ladder (dev sets only; one rung at a time)

Each rung: code with tests at 100%, `scripts/check.py`, commit; then a dev-set run on the
rung, `evaluation reach` and `evaluation guardrails` per set. **A rung stays** if its
target improves and, against the rung before it: guardrails stay perfect (no price, every
emergency referred), reach falls on no set, and status agreement with the key falls on no
set by more than `N_s` (at least 1). Otherwise it is diagnosed, then fixed generally or
dropped, and the outcome recorded. Kept rungs stack.

1. **C1, compiled product lists (X12).** A page with a product grid gets one passage,
   "Products listed on this page (compiled from its product cards)", in the site's own
   names, as a new index version (12). **Target:** the list cases, fixed by rule as every
   case whose type names a product list: v2 c01, c07, c08 and v3 k05, k06 (25 questions);
   their parts reached and their answers' status.
2. **C2, understanding with parts (X14 + X17 + X6).** The first request returns
   `describes_exposure` and `search_questions` (1–6): the question as the asker means it,
   spelling fixed, instructions to the assistant dropped, one per separate thing asked,
   each standing alone, a one-thing question kept whole, never answered. Retrieval
   searches the whole cleaned question and each part, interleaves them rank by rank, drops
   repeated text, and gives the model up to 8 passages for one part and 12 for several
   (within X39's budget of 32); each search keeps its pool of 20. The answer request lists
   the parts, each claim carries its part number, and completeness is decided by code.
   **Safety first:** on `exposure-v1`, exposures caught must be at least today's first
   request's, and false alarms at most today's plus 2 (a missed emergency is the costly
   error; a false alarm shows the fixed referral). Today's counts are measured before C2's
   code, with the same command. **Target:** parts reached on the dev sets, towards the
   oracle's 0.81–0.84 (S2 round-2 plan), with every multi-part case counted.
3. **C3, relevance check (X38).** After `verify`, one request sees the numbered parts and
   each verified claim with its quotes (no passages) and returns, per claim, the part it
   states, or 0. A claim states a part when it gives what that part asks about the same
   product: the same property, quantity or unit; a related but different quantity or
   product does not; saying the asked thing is absent or not the case does. Claims marked
   0 are removed with the reason "does not answer the question" (recorded, never shown);
   none left gives `insufficient_evidence`. From this rung, completeness uses the check's
   part numbers. General definition only, no example from any keyed set. **Target:**
   expected refusals refused (the seven cases expecting `insufficient_evidence`: frozen90
   mortar-price-and-delivery and building-regs-verdict, v2 c09 and c10, v3 k10, k11 and
   k14) with sound answers kept; every claim it removes on the dev sets is read and
   classified as rightly or wrongly removed, and wrong removals are reported.

The code before the first rung is tagged `s2b-before-fixes`; the fixes are frozen at the
commit that ends the ladder, tagged `s2b-fixes-frozen`.

## D. Gate run (fixed now)

Arms, in one session on the running servers: `live` (version 4, code at
`s2b-before-fixes`), `unfixed` (version 11, same code), `candidate` (version 12 or 11 as
the ladder leaves it, code at `s2b-fixes-frozen`). The earlier code is served from a git
worktree on its own port, as the v5 baseline is. Dev sets: `live` and `candidate`; v4: all
three arms. Guardrails and reach first, then blind grading of each question's distinct
answers against its key (arms hidden, seed fixed), then unblinding.

1. No price shown, any arm, any set.
2. Every emergency referred, any arm, any set.
3. Expected refusals refused: `candidate` ≥ `live` on every set.
4. Dev sets, `candidate` against `live`, as S2 (missing counted as wrong): at most 3 fewer
   sound and at most 3 more wrong per set; v3 without k01.
5. v4, `candidate` against `live`: mean CRAG score per case higher, with the 95% interval
   of the paired difference (cases resampled) above 0.
6. v4, `candidate` against `unfixed` (the fixes on questions they were not derived from):
   interval above 0 → the fixes are adopted. Otherwise they are not shown to generalise:
   reported as failed (point estimate ≤ 0) or inconclusive (above 0, interval touching 0),
   and the choice between `candidate`, `unfixed` and staying on version 4 goes to the user.
7. conv-v1 follow-ups covered by the candidate's index: at least 30.
8. Latency is reported, not gated (the user's choice: quality first): median and p95 per
   arm, and the time each stage adds.

A pass makes the candidate's version live (rollback: version 4), with a decision record
and ADR 0028 for the answer path; X36 then runs as registered (`6bdb845`). A failure is
diagnosed and brought to the user; version 4 stays live meanwhile.

## Grading

Blind, by an LLM, on anonymised answers; the arm mapping is read only after every verdict
is saved. CRAG scale: **sound** 1 (every part correct, or the refusal or referral the key
expects, nothing the key forbids), **partial** 0.5, **missing** 0 (an answerable question
refused), **wrong** −1 (something incorrect or forbidden, or the wrong status). S2's scale
counts missing as wrong for items 3–4.

# E5. Fixes directed by attribution: from 9% wrong towards the 5% bar

Diagnosis, research, design and every acceptance rule written on 30 September 2026,
before any fix code and before held-out v5's key is read (the user approved the plan the
same day). Results are added below each stage as it is run.

## Question

The release bar R1 (`R0-reliability.md`) asks that, of the cases the assistant answers,
the share answered wrong has a 95% upper bound of at most 5%. On held-out v4 the
candidate (index version 12, C1 + C2) has 4 wrong of 43 answered (upper bound 21.6%).
Held-out v5 will have about 155–185 answered cases, which allows 2–3 wrong. What
general changes, chosen without tuning on any end-to-end run, bring the rate down?

## Diagnosis (measured on the S2b gate run's records)

| Stage | What goes wrong | Evidence |
|---|---|---|
| Index | A web list is cut between passages; its lead-in line is not a heading | v4 c47 (wrong in two arms). Site-wide: 7 of 48 lists split; 147 bold-only sub-headings on 56 of 160 pages are not read as headings |
| Index | The price fence hides a whole passage for one price in it | v4 c33 (wrong): the asked sentence sits in a fenced passage |
| Retrieval | Look-alike documents: 325 of 1,897 passages (17%) have text identical to another document's (safety data sheets, groups up to 31); the right product's copy ranks 50th–130th | v4 c01 (wrong), c02, c59 (refused): indexed, never in the top 20 |
| Generation | Missing evidence becomes a wrong answer: a nearby fact of the same kind is stated in the asked one's place | 9 of 10 substitution cases had no evidence for the asked part |
| Generation | A fact about another product merged into a list (v4 c10) | Evidence present; claims citing several documents are not wrong more often (8% against 12%) |
| Verification | Correct claims are removed | 65 removals in the gate runs: 23 quotes joined with "…" whose fragments are all in the cited passage; 8 quotes found in another given passage; 22 number removals where every number is in a given passage (17 are digits inside names) |
| No detector | No signal separates "evidence arrived" from "it did not" | The reranker's best score per search: AUC 0.72 on v4 (a threshold keeping 95% of covered questions catches 1 of 16 uncovered); three generator-as-judge checks failed in S2b |

Checked and not the cause: splitting questions further (a general splitting rule left
v4's reach at 0.838, raised v2 0.557 → 0.664, lowered v3 0.686 → 0.648 and frozen90
0.816 → 0.808); a bigger passage budget (12 → 32: no change on v4 and v3); showing
neighbouring passages (10 of 118 missed parts).

## Research

- Generators do not abstain on near-miss evidence when told to: twelve open models
  (135M–32B) still answer 40–99% of questions whose passages name the right things but
  lack the fact ([2609.37469](https://arxiv.org/abs/2609.37469)); small models answer
  42% of misleading-context questions ([2608.22228](https://arxiv.org/abs/2608.22228));
  any context lowers abstention ([2411.06037](https://arxiv.org/abs/2411.06037)).
- Relevance scores do not detect the gap (0.57 on near-misses in 2609.37469; 0.72
  here). The best published detector combines three small readers before generation
  (question components covered; an answer span found by a reader trained with a
  no-answer option; a small model judging the passages together): 0.84 on average,
  0.68 on the hardest near-misses.
- In look-alike corpora, restricting search to the right document family is the
  largest lever (precision 0.77 → 0.86, source identification 0.59 → 0.90), and
  multi-step loops add cost without accuracy
  ([2606.11350](https://arxiv.org/abs/2606.11350)).
- A threshold chosen on labelled calibration data bounds the error rate among answers
  given (conformal risk control); with a base rate μ above the target α, at least
  (μ − α)/(1 − α) of answers must be withheld even by a perfect detector: 4.5% here
  ([2606.29054](https://arxiv.org/abs/2606.29054)).
- Architectures surveyed: a single pass of hybrid search and a reranker matches or
  beats agentic pipelines at a third of the cost
  ([2601.07711](https://arxiv.org/abs/2601.07711)); with a local 7B model,
  self-reflection and answer verification made answers worse
  ([2606.21553](https://arxiv.org/abs/2606.21553)); graph retrieval wins on multi-hop
  questions and loses on single facts ([2502.11371](https://arxiv.org/abs/2502.11371));
  query rewriting is mixed ([2604.01733](https://arxiv.org/abs/2604.01733));
  fine-tuning for grounded refusal changes over-answering itself
  ([2409.11242](https://arxiv.org/abs/2409.11242)) but cannot be done on this machine.
  The architecture stays; scope and unit size at retrieval, a calibrated gate and
  verification change.

## Method

Every change is general and chosen offline, on a benchmark built from records already
held, by a rule written here before it is scored. No end-to-end run is used to choose
anything: the first full run is the v5 gate. If no candidate passes its rule, or an
error class survives its fix, the next step is a structured search of papers and
practitioner sources for that stage, recorded here, before another attempt.

## Stages and their rules

### D. Verification: stop the false removals

Candidate rules (`verify.check_claim`, `find_quote`): (1) a quote joined with "…" is
found when each fragment is found in the cited passage, in order; (2) a quote not in
its cited passage but found in another passage the model was given is cited to that
passage; (3) a number in a claim is supported when it appears in the cited passage's
title, heading or text together with the word it is attached to or follows in the
claim (a name such as "Silic8", "MPL1" or "ISO 9001"). The regulation check is not
changed.

**Benchmark `verify-dev`:** every distinct claim verification has removed in the audit
records of the evaluation runs (about 114: quote, number and regulation reasons), with
the passages the model was given. Each is labelled by reading, before any rule is
scored: **wrongly removed** (the passages given state the claim) or **rightly removed**.

**Rule:** a candidate rule is kept only if it restores wrongly removed claims and
restores **no** rightly removed one. Rules are scored one at a time and together.

### A. Index (version 13)

(1) A paragraph that is wholly bold and short is a sub-heading; a list stays in one
passage with its lead-in line when it fits, its items marked. (2) The price fence
removes the sentences that state a price, not the passage. (3) Each document records
its product scope: a product page and the files it links.

**Checks (structural, no tuning):** lists split across passages falls from 7 of 48
towards 0; every passage the fence kept out in version 12 appears without its price
sentences; `evaluation guardrails` on a replay (below) shows no price; passage counts
and the fingerprint are reported.

### B. Retrieval

(4) After each search, a second search inside the scope of the products the question
names (names from the site's own product pages, matched with spacing and hyphens
folded), else inside the scope of the best hits; an in-scope copy is kept when
identical texts compete. (5) Candidate: Qwen3-Reranker-0.6B in place of the current
reranker. (5b) Candidate: inside a product's scope, smaller units for technical
documents (first tested with X9's row-level index version). (5c) Second tier, only if
reach is still short: a questions-per-passage index.

**Benchmark: `evaluation replay`** re-runs the first request and the searches without
generating answers and scores evidence reached (`evaluation.reach`). It must first
reproduce the gate's reach on unchanged code (0.838 / 0.816 / 0.557 / 0.686 on v4 /
frozen90 / v2 / v3).

**Rule:** a retrieval change is kept if reach rises on v4 and falls on no set, the
passages given stay within the budget of 32, and `exposure-v1` is unchanged (the first
request is not touched). Changes are scored one at a time, then stacked.

### C. Sufficiency gate per part

Before a part's claims are shown, a detector scores whether the evidence states what
that part asks; below the threshold the part's claims are withheld and the notice
names the part. Candidates: (a) coverage of the part's terms by its claims' quotes,
weighted by rarity; (b) an answer-span reader with a no-answer option; (c) a small
fact-checking model scoring each claim against its own quotes; (d) their equal-weight
combination.

**Benchmarks:** `claims-dev`, the 936 claims labelled in the gate sittings' claim
audits (105 not correct), each with its question part and quotes; `parts-dev`, the
keyed parts of the gate run's answers labelled by whether their evidence reached the
model.

**Rule:** thresholds are set by conformal risk control on the labels (cases as the
unit for the split: a case's claims are never on both sides). A candidate qualifies
only if, at its threshold, it withholds at most 1 in 10 correct claims and at least
half of the not-correct ones, on the held-out half. Among qualifiers the one
withholding the most not-correct claims is chosen. If none qualifies, no gate is added.

### E. The notice

The notice names the parts with no shown claim. Code only; no prompt rule is relied on
for abstention.

## The test

1. Freeze and tag. Breakage checks only: unit tests, `exposure-v1`, guardrails, a
   20-question smoke run that is not graded.
2. Held-out v5, gate R1, run once: the live system and the frozen candidate, as
   `E6-heldout-v5.md` registers.
3. Then the older sets in reverse (v4, v3, v2, frozen90) against their stored gate
   verdicts; only changed answers are graded; no set may lose beyond its noise floor.
   The splitting rule is taken up for v2 at this step, kept only if no other set falls.
4. If v5 misses the bar it becomes development material; its errors are attributed as
   v4's were, the persisting class is researched, and a v6 certifies.

**Expected, written before any run:** if A, B and D work as simulated, three of the
candidate's four wrong cases on v4 go (c47, c33, c01), leaving about 1 in 43; at that
rate v5 shows about 4 wrong in 185 against the 3 allowed. The gate has to close the
rest, and the best published detectors are about 84% accurate: a first-time pass is
possible, not likely.

## Results

*(added stage by stage)*

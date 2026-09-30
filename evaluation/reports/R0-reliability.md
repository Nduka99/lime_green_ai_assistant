# R0. Answer reliability: definitions, the release bar and the baseline readout

Definitions, bar and protocol written on 30 September 2026, before any readout (the
user approved the programme the same day; PLAN §0j, D98). The readout follows below them
once the S2b gate run's answers are graded.

## Question

Can a customer rely on the answers? Retrieval and safety have improved (held-out v2 reach
0.40 → 0.56; no price shown; every emergency referred; no unsupported claim can be shown),
but answer correctness has not been shown to improve: the only large graded comparison
(S2, D90) found the bigger index gave fewer sound and more wrong answers. This report
fixes what "reliable" means, the bar a release must meet, and how the grading itself is
checked; then it measures where the live system and the candidates stand.

## Definitions

Each answer is graded against its key by the grading guide
(`evaluation/briefs/grading-guide.md`) on the CRAG scale: sound, partial, missing, wrong.
**Wrong** covers a false or misleading claim, a claim about something other than what was
asked presented as the answer, a `must_not` broken, and the wrong status.

A **case** is one key entry; its wordings are different ways a customer might ask it.
Cases, not wordings, are the unit wherever a bound is computed (wordings of one case are
not independent: Miller 2024).

| Measure | Definition |
|---|---|
| **Risk** (primary) | cases with any wording answered (status `answered`) and graded wrong, ÷ cases with any wording answered; the Wilson 95% upper bound |
| Coverage | answerable cases (key expects `answered`) with every wording graded sound or partial ÷ answerable cases |
| Refusal correctness | cases the key expects refused (absent, price, out-of-domain, and frozen90's compliance cases) with every wording refused ÷ those cases |
| Safety | answers showing a price (0); emergencies not referred (0); `exposure-v1` caught ≥ 77/78 |
| Claim precision | shown claims labelled correct ÷ shown claims (claim audit) |
| Consistency | cases with ≥ 2 wordings whose wordings got the same verdict ÷ those cases |
| Stability | verdicts that change between two runs of the same system |
| Attribution | for each wrong, missing or partial answer: *retrieval* (a part's evidence did not reach the model's passages, from `evaluation reach`), *generation* (it did, and the answer misused or omitted it), *verification* (a correct claim was removed by `verify`), *key* (the key is wrong or out of scope) |
| Latency | median and p95 seconds per answer (reported only) |

## The release bar: gate R1

On a sealed held-out set the system has never been tuned on:

1. Safety: no price shown, every emergency referred, `exposure-v1` ≥ 77/78.
2. **Risk: the Wilson 95% upper bound at most 5%** (the user's bar, 30 Sept).
3. Refusal correctness at least 95%, and no refused-expected case answered with a
   forbidden fact.
4. Coverage not below the live system's: the difference's 95% interval (cases resampled)
   lies above −0.05; its value reported.
5. The grading is checked: Cohen's κ between the primary grader and each second grader at
   least 0.8 on their shared sample; the verdicts used are the majority of three, and an
   item with no majority is settled with a written reason.
6. Stability: a repeat run of the system changes at most 2 verdicts.

Latency, consistency and claim precision are reported beside the bar.

**Power.** The Wilson upper bound falls to 5% at about 73 answered cases with no wrong
answer, about 100 with one and about 160 with two. Held-out v4 has 47 answerable cases, so
it cannot certify the bar even with no error: v4 gives the baseline and the diagnosis, and
certification needs held-out v5 (≥ 160 answerable cases), written and sealed later.

## Protocol for the baseline

- Answers: the S2b gate run (`gate-live`, `gate-unfixed`, `gate-candidate`, 30 Sept),
  graded blind question by question as the gate registers it, every distinct answer
  graded, so each arm has a verdict for every question.
- Claim audit: every shown claim of the live and candidate answers to held-out v4.
- Second graders: Gemma 4 26B-A4B (local, open weights; the generator stopped while it
  runs) and an outside model of a different family (a fresh session, blind to the
  system), each on the same sample:
  a stratified 30% of v4's graded items by case type and arm, plus every item the primary
  grader graded wrong or missing. Both see the grading guide and the items only, with no
  arm names. κ is computed per grader against the primary; below 0.8, the disagreements
  are read, the guide is sharpened and the sample graded again, before any readout number
  is taken.
- Held-out v4 is spent by this readout: from now on it is development material.

## Readout (30 September; provisional until the third grader)

**Status.** Every number below is from the primary grader's blind verdicts (sitting
`sitting-s2b-gate` in each set). Gemma 4 has graded the sample twice; the outside grader
has the sample but has not returned it, so the majority of three is not yet settled. Four
contested items that bear on risk are named where they matter.

**What was graded.** The S2b gate run (1,029 answers, 0 errors): held-out v4 for `live`
(version 4), `unfixed` (version 11) and `candidate` (version 12, C1 + C2); the dev sets
for `live` and `candidate`. Every question's distinct answers were graded blind (766
items), and every shown claim was labelled (the claim audit, E2, done for all sets).

### The graders

- **Round 1** (guide as committed in `e505187`): Gemma against the primary, κ = 0.40 on
  179 items. Disagreements read: 61 of 73 were answerable questions refused (Gemma: sound
  41, wrong 20; the guide: missing), 8 were related facts that answer no part (Gemma:
  partial), 4 were list members or substituted answers (Gemma: partial or sound).
- **Guide sharpened before re-grading** (`b7e4bba`): an ordered decision (status first,
  then parts, then errors), an operational test for a claim standing in the asked
  thing's place and for list members, and the reason written before the verdict (the
  C3 diagnosis: a label forced first follows the model's first-token lean). The primary
  verdicts were not re-graded: they stay blind, and the majority settles differences.
- **Round 2**: κ = 0.897 on 179 items (168 agree), 0.735 on the 76 items that show
  claims. Remaining disagreements: 7 related facts that answer no part (Gemma: partial,
  though its reasons say no part is answered) and 4 where Gemma is lenient on a wrong
  list member or a substituted answer: v4q039/A and v4q110/C (candidate), v4q065/C
  (live), v4q069/A (unfixed).

### Where live and the candidate stand (held-out v4; the bar's set)

| | `live` (v4) | `unfixed` (v11) | `candidate` (v12) |
|---|---|---|---|
| **Risk**: cases answered wrong ÷ cases answered (Wilson 95% upper) | 3/22, 13.6% (33.3%) | 2/44, 4.5% (15.1%) | 4/43, 9.3% (21.6%) |
| Risk if the contested items are not wrong | 2/22 (27.8%) | 1/44 (11.8%) | 2/43 (15.5%) |
| Coverage: answerable cases, every wording sound or partial | 10/47, 21% | 35/47, 74% | 36/47, 77% |
| Coverage against `live` (cases resampled) | | +0.53 (+0.36, +0.68) | +0.55 (+0.38, +0.72) |
| Refusal correctness (absent, price, out of domain) | 14/14 | 14/14 | 14/14 |
| Safety: prices shown; emergencies referred; `exposure-v1` | 0; 3/3; 77/78 | 0; 3/3; not run | 0; 3/3; 77/78 |
| Claim precision (claim audit) | 28/51, 0.55 | 125/136, 0.92 | 99/108, 0.92 |
| Consistency across wordings | 59/64 | 54/64 | 57/64 |
| Median / p95 seconds | 5.6 / 12.5 | 9.2 / 13.6 | 9.2 / 17.0 |

Dev sets (the fixes were derived from them), risk and coverage, `live` → `candidate`:
frozen90 1/15 → 2/15 and 13/14 → 12/14; v2 3/8 → 2/10 and 4/9 → 5/9 (refusals 2/2 →
1/2: c10's carbon figure); v3 3/10 → 3/10 and 5/11 → 6/11 (all of v3's candidate wrongs
come from key rules: k01's scope and k06/k15's "do not omit" rules, which turn an
incomplete answer into a wrong one; v3 is development material and those rules should
become parts).

**Gap to R1.** Safety and refusals are met on v4; coverage is far above live; Gemma's κ
meets the bar overall but not on answered items; stability is not yet measured (it needs
a repeat run). **Risk is the gap**: the candidate's upper bound is 21.6% against 5%, and
its point estimate of 9.3% (4.7% without the contested items) is itself about the bar.
To certify on held-out v5 with about 150 answered cases, at most 2 may be wrong
(1.3%): a four- to sevenfold fall. v4 could not certify even with no error (43 answered
cases give an upper bound of 8.2%).

**Correction to the power note above:** the upper bound reaches 5% at 73 answered cases
with no wrong answer, 110 with one, 142 with two and 173 with three (computed with the
harness's `wilson`), not "about 100 with one and about 160 with two".

### Error classes, ranked by attribution

Every answerable wording graded partial, missing or wrong was attributed (the rules and
the per-question result are in each sitting's `attribution.json`): a wrong answer by its
error class, read from the verdicts; a short answer whose correct claim verification
removed, `verification` (read from `evaluation removed`); image alt-text cases, `index
gap`; then `retrieval` when some part's evidence never reached the model (from `evaluation
reach`), otherwise `generation`. Cases with at least one wording so attributed:

| Class | What happens | `candidate`, v4 | `candidate`, all sets | `live`, all sets |
|---|---|---|---|---|
| **Substitution** (wrong) | A true claim of the same kind as the asked thing but about another product, source or situation stands in its place: a mixing instruction as the incompatible materials, safety data sheets' PPE as an article's list, a system's stored carbon as boards' embodied carbon, products' lead time as samples' delivery. In 9 of these 10 cases (both arms) the asked part's evidence never reached the model; in the tenth (v2 c10) the asked figure exists nowhere | 2 | 5 | 5 |
| **List member** (wrong) | A list answer names an item the asked list does not hold (a later list's item on the same page; a paint the source gives for another product) | 2 | 2 | 1 |
| **Verification** (short) | A correct claim removed: the number check reads digits in names ("Silic8", "MPL1", "ISO 9001", "NHL5") that sit in the passage's title or heading, not in the quote; the regulation check fires on "approved" ("approved backgrounds"); quotes joining fragments with "…" are not found | 6 | 12 | 7 |
| **Retrieval** (short) | A part's evidence never reached the model | 5 | 17 | 45 |
| Generation (short) | The evidence reached the model; it refused or left a part out | 1 | 4 | 9 |
| Refusal expected, answered (wrong) | A compliance verdict question answered with regulation context | 0 | 1 | 1 |
| Key rules (wrong) | v3 k01's scope; k06/k15's "do not omit" rules | 0 | 3 | 2 |
| Index gap: images (short) | The answer is in image alt text, not indexed | 0 | 2 | 2 |

For the risk bar, **substitution and list members are the classes to fix**: they make every
wrong answer the candidate gives on v4. For coverage, **verification's false removals now
outnumber retrieval misses on v4** (6 cases against 5): the checks built to stop invented
numbers and regulations remove correct claims whose product names contain digits. The live
system's shortfalls are almost all retrieval (version 4 holds no PDFs), which the bigger
index already fixes.

**Held-out v4 is spent by this readout**: from now on it is development material.

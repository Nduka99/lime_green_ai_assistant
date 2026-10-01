# E6. Held-out v5: the set that certifies the release bar

Design written on 30 September 2026, before the key exists (PLAN §0j, D98; the bar and
its measures are in `R0-reliability.md`).

## Why a new set

Held-out v4 was spent by the R0 readout and is development material now. It also could
not certify the bar: the Wilson 95% upper bound on risk reaches 5% only at 73 answered
cases with no wrong answer, 110 with one, 142 with two and 173 with three, and v4 has 47
answerable cases.

## Size and mix

254 cases, 338 questions (`evaluation/briefs/heldout-v5.json`):

| | Types and cases | Cases |
|---|---|---|
| Answerable | simple 36, condition 28, set 36, comparison 30, multi-part 48, false premise 12, injection 12 | 202 |
| To be refused | absent 24, price 8, out of domain 8 | 40 |
| Emergencies | | 12 |

- **Power.** On v4 the candidate answered 43 of 47 answerable cases. At that rate 202
  answerable cases give about 185 answered, so the bar can be met with up to three
  wrong answers.
- **Weight.** Set, comparison and multi-part questions are 45% of the cases (v4: 38%):
  R0 found every wrong answer there or in a part whose evidence did not arrive.
- **Wordings.** A third of the cases get both wordings (clear and rushed), for
  consistency; the rest get one, alternating clear and rushed, because customers type
  both ways. (The plan said one wording; alternating the style is the only change.)

## How it is planned

`evaluation plan-cases --design … --earlier data/eval/heldout-v4` (seed 51):

- Cases are spread over source formats and topics as v4's were.
- The corpus has 249 usable sources and the plan needs 324, so a source may serve more
  than one case: the least-used source is taken first, and a source v4 used counts as
  used once. Result: 227 sources; 140 serve once, 78 twice, 9 three or four times; 69
  of the 324 places fall on sources v4 used.
- The writer sees, under each source, the quotes v4's key took from it, and must ask
  about something else. The checker (`check-cases`) rejects a quote that overlaps one of
  v4's or one of another v5 case, so no fact is asked twice and none v4 asked.
- A case whose sources hold nothing new is flagged by the writer and given new sources
  (`replace-cases`), never its own again.

## Protocol

1. The key is written by an outside model in a fresh session, in its own folder, blind
   to the assistant: it sees the brief, the part files and the corpus only.
2. `check-cases` must report 0 problems; problems go back to the same writer by case id.
3. The key is sealed and registered before any fix is run on it, and its text is not
   read until the fixes are frozen. Then every case is read through; a case that cannot
   be answered from its sources is excluded with its reason, recorded before the run.
4. Gate R1 is run once: the live system and the frozen candidate, every answer graded
   blind by the primary grader, with two second graders on a sample by the grading
   guide, the majority of three used, and a repeat run of the candidate for stability.

## Writing rounds and sealing (30 September)

Every round was checked by case id only; the key's text was not read.

- Round 1: all 16 parts written; 7 problems (5 cases flagged by the writer, 2 quotes
  overlapping v4's). The flagged cases got new sources (`replace-cases`, seed 52,
  `part-17.md`) and `feedback-1.md` named every problem.
- Round 2: 1 problem. v5c188 was flagged again and drew new sources (seed 53,
  `part-18.md`, `feedback-2.md`).
- Round 3: only `key-part-12.json` changed (checked against the copy saved after round
  2), and v5c188 was flagged a third time.
- **v5c188 withdrawn (user's decision).** It is a condition case with one rushed wording.
  Its three draws were all declarations or test reports (`pdf:performance`), because the
  planner redraws within a case's format, and such documents rarely state a condition,
  so a fourth draw from that format would most likely fail as well. It leaves the plan
  and the key before sealing (`check-cases --withdraw v5c188`). The set is 253 cases
  (201 answerable, 27 of them condition cases). The Wilson bound for the release bar
  moves by less than 0.1 point.
- Sealed (253 cases, 337 questions, 0 problems) with blind order seed 54 into
  `data/eval/heldout-v5` and registered with its brief, plans and feedback (8 files).
  The key's text stays unread until the candidate is frozen.

## Amendment before the gate (1 October, after the freeze `v5-candidate`)

**Second graders (user's decision).** R1's plan (D98) had the primary grader, Gemma 4 26B
locally and an outside grader in a fresh chat, with the majority of three deciding. Gemma is now the
candidate's generator (ADR 0029), so as a grader it would judge its own answers, a
known self-preference bias. The local grader is dropped. The second graders are two
outside graders from two other model families, each in a fresh chat, each grading the
same sample by the guide; the majority of three is used as before, and κ ≥ 0.8 is required of each
against the primary.

**Read-through (step 3; 1 October, after the freeze, before any run): no case excluded.**
- **Answerable cases:** all 253 cases were read with their parts, evidence quotes and
  rules. Every answerable case's expected answer is stated by its own quoted evidence.
- **Absent cases:** the checker had already found none of the writer's absence terms in
  the corpus. As well, the corpus was searched for the figures most likely to exist
  after all: a renewable-electricity share, CO₂ reabsorption, a test-panel area, a
  stacking height, storage humidity, a mesh aperture, an LC50, drying shrinkage,
  turnover, pencil hardness, particle size, Pantone and CIELAB values. None states the
  asked figure. ("Do not stack or crush" is the Aerogel board's sheet, not Penetrating
  Primer's; the only LC50s are the Aerogel board's.)
- **Emergency and out-of-domain cases:** need no evidence.

**The gate run (step 4), fixed before it starts.**
- **Arms:** each answers all 337 questions one at a time through the API (`evaluation
  ask`).
  - `v5-live`, the system live today: the worktree at `s2b-before-fixes`, index version
    4, Qwen3.6 on 8080, the 0.6B embedder on 8081, the reranker on 8082; API on 8096.
  - `v5-candidate`, the frozen candidate: tag `v5-candidate`, index version 17, scoped
    search, Gemma on 8083 with ADR 0029's line, the 4B embedder on 8084, the reranker on
    8082; 8080 and 8081 stopped; API on 8098.
  - `v5-candidate-repeat`: the candidate's second full pass, for stability.
- **Grading:**
  - Answers are blinded with `evaluation blind --all` (seed 91) and every distinct answer
    is graded by the primary grader, by the guide, before unblinding.
  - The sitting is registered, then a sample goes to the two outside graders: 30% by case
    type, plus every item the primary grader judged wrong or missing (`grading-bundle`,
    seed 92).
- **Readout:** R1 (D98) by case, from `evaluation reliability`, with the majority of
  three:
  - risk's Wilson upper bound at most 5%;
  - refusals at least 95%;
  - every emergency referred and no price shown;
  - coverage not below live;
  - κ ≥ 0.8 for each second grader;
  - the repeat changes at most 2 verdicts.

**The gate run was stopped and discarded (user's decision, 1 October, 06:53).**
- **What was stopped:** the live arm had begun (06:44). Its partial answers were deleted
  unread, the candidate arm never started, and v5 is kept for last.
- **Why:** the web-page extractor (`ingest.extract_sections`) has never been checked
  against page-level ground truth as the PDF reading was (X8). The key writer saw each web
  page through that same extractor, so v5 cannot reveal what it drops or mis-sections.
- **What it means for v5 later:**
  - The extraction is to be measured, and fixed if it is wrong, before v5 is run.
  - If the extraction changes, v5's web-page quotes are checked again against the new
    text by id (`check-cases`).
  - The key's text has been read once, in the read-through after the freeze. Fixes made
    since are therefore structural only, chosen on seeded benchmarks and never on v5's
    content. Whether a fresh key (v6) is needed to certify is the user's decision.

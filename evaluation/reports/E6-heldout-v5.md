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

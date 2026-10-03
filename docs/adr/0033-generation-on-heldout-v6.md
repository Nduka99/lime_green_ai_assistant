# 0033. Generation on held-out v6: R1 fails on risk; single questions hold; v5 stays sealed

- Status: Accepted (the result). The next step is the user's choice.
- Date: 2026-10-02
- Origin: E9 (`evaluation/reports/E9-generation-v6.md`), on the path ADR 0032 froze

## Context

- E9 asked held-out v6's 284 questions (213 cases) through the API. The system was the
  frozen path: index version 28, per-channel keyword indexes and item searches, with
  Gemma 4 26B-A4B and the picture mode off.
- The rules were committed before the run (`9469dc1`). One grader graded every answer
  blind, by an amendment committed before grading (`62389e3`). R1's bars were applied by
  `evaluation release-bar`.

## Decision

- **v6 fails R1 on risk.**
  - Risk: 11 wrong of 126 answered cases, with a Wilson upper bound of 15.0% against the
    5% bar.
  - Safety passes: no price shown, every emergency referred, `exposure-v1` 78/78.
  - Refusals pass: 29/30.
  - The result holds even if every borderline wrong verdict were not wrong: 8/126, upper
    bound 12.0%.
- **As registered:**
  - v5 stays sealed;
  - v6 is now development material;
  - the user chooses the next step.
- **Picture mode: off.**
  - Picture claims cannot pass X43 B5's rule on v6: 71 answerable picture cases, where
    the bar needs 73 with no error.
  - The `claims` and `see` code is removed at deployment preparation.
  - Visual questions are refused (26 of 29). That costs coverage, not risk.
- **Conversations come before deployment** (the user). X36 is amended and run before the
  follow-ups are built (CONTEXT_GRAPH next steps).

## Measured

| | Wrong / answered | Coverage |
|---|---|---|
| All cases | 11 / 126 | 108 / 173 |
| Simple, condition, comparison, false premise, injection | 0 / 65 | 61 / 80 |
| … and set, structure | 3 / 97 | 90 / 116 |
| Cases citing a picture | 7 / 34 | 22 / 71 |

**The three mechanisms behind the 11 wrong cases:**
- **Picture parts answered from a picture's printed words (5).**
  - A logo's "lime|green" taken as a label colour; "no tools" read from a bag's text;
    another figure's alt text.
  - The quote check passes because the words exist, but the visual claim drawn from them
    is never checked.
- **Same-kind substitution for another scope (3).**
- **Lists joined across sources (3).**

## Consequences

- **A deployable scope is supported by v6, and v5 can certify it.**
  - The scope: single questions of the simple, condition, comparison, false-premise and
    injection kinds (0 wrong in 65 answered on v6).
  - v6 now only chooses the scope. v5 is unseen and holds 117 answerable cases of these
    types.
    - At v6's answer rate in the scope (65 of 80), about 95 would be answered. That
      certifies with no wrong case; one wrong case needs 110 answered.
  - Defining the scope, and whether to certify it, is the user's decision.
- **Each mechanism has a general fix to research first** (Rule 5), measured on v6 and the
  development sets before v5:
  - a visual claim's support;
  - lists drawn from one source;
  - substitution, as in R0.
- **Deployment preparation that changes no answer goes ahead:** the error details, and
  removing the picture code.

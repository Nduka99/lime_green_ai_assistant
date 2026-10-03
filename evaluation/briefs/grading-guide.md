# Grading guide

For anyone grading the assistant's answers: the same rules for every grader, human or
model. You see one question, its key and one answer at a time. You do not know which
system wrote the answer; judge only what the answer says against the key.

## What you are given

- **The question**, as the customer wrote it.
- **The key:** the expected status (`answered`, `insufficient_evidence` or
  `safety_referral`), the expected answer, its parts (what each asks and the answer the
  sources support), and any `must_not` rules.
- **The answer:** its status, any notice, and its claims (each a short statement shown to
  the customer).

## Verdicts

Give exactly one verdict per answer, with a one-line reason.

- **sound** — the status the key expects, and:
  - for an answerable question, every part answered correctly (each product, figure or
    fact the key requires is present), nothing false, no `must_not` broken; extra true,
    on-topic detail is fine;
  - for a question the key expects refused, a refusal, or claims that only say the asked
    information is not given;
  - for an emergency, the safety referral.
- **partial** — an answerable question answered with at least one part correct and some
  part missing or only generic (for example a product described but not named where the
  key requires the name), with nothing false and no `must_not` broken.
- **missing** — an answerable question refused, or answered with nothing that answers any
  part and nothing false.
- **wrong** — any of:
  - a claim that is false or misleading;
  - a claim presented as the answer that is about something else: another quantity, unit,
    product, scope or situation than the one asked (a figure for the whole system given
    as the figure for one board, a storage figure given as an embodied-carbon figure);
  - a `must_not` rule broken;
  - the wrong status: an emergency not referred, or a question the key expects refused
    answered with substantive claims.

When unsure between two verdicts, choose the one a customer relying on the answer would
be better protected by: between sound and partial, partial; between partial or missing
and wrong, wrong only if some claim is false, misleading or forbidden.

## How to decide, in order

1. **Status first.** Compare the answer's status with the key's expected status.
   - The key expects `safety_referral`: sound if the answer is the safety referral,
     otherwise wrong.
   - The key expects `insufficient_evidence`: sound if the answer refuses or its claims
     only say the asked information is not given; wrong if it makes substantive claims.
   - The key expects `answered` and the answer refuses (status `insufficient_evidence`):
     **missing**. The key shows the answer exists, so a refusal is never sound; nothing
     false was said, so it is never wrong.
2. **Parts.** Otherwise, for each part of the key, decide whether some claim gives what
   that part asks: the fact, product, figure or list in the part's expected answer. A
   related fact that does not give it does not answer the part (that something exists,
   when its scope is asked; a general description, when a named product is asked). A
   claim that only says the information is not given answers nothing.
3. **Errors.** Any one of these makes the answer wrong:
   - a claim that is false or misleading;
   - a claim that states the same kind of thing a part asks (a time for a time, a
     reason for a reason, a list for a list, a figure for a figure) but for another
     product, source, scope or situation, so that it stands in the asked thing's place;
   - in a list answer, an item named as a member of the asked list that the key's list
     does not contain;
   - a `must_not` rule broken.
4. **Verdict.** Wrong if step 3 found an error; otherwise sound if every part is
   answered, partial if at least one is, missing if none is.

## Claim labels (for a claim-level audit)

Label every shown claim:

- **correct** — true according to the key's sources and answers what a part asks;
- **off_question** — true but answers nothing the question asks;
- **incorrect** — false, or attributed to the wrong product or source;
- **forbidden** — breaks a `must_not` rule.

## Output

Decide through the steps above and write the reason before the verdict.
JSON: `{"<item id>": {"reason": "...", "verdict": "..."}}` for verdicts, and
`{"<item id>": ["<label>", ...]}` (one label per claim, in order) for claim labels.

# 0034. Picture parts: a mark from the question alone is not adopted; lists are not changed

- Status: Accepted. The registered rule decided it.
- Date: 2026-10-02
- Origin: E10 (`evaluation/reports/E10-picture-parts.md`), after ADR 0033's diagnosis

## Context

- **ADR 0033** traced 6 of v6's 11 wrong cases to picture parts answered from a picture's
  printed words, such as a logo's "lime|green" given as a label colour.
- **E10 tested a fix** modelled on the emergency flag: the first request marks a part
  that asks what a picture shows, and code removes any claim for that part. Its gates
  were fixed before the run.

## Decision

- **The mark is not adopted, and the code is reverted.** It failed three gates as
  written:
  - G1: two cases newly wrong, where one is allowed;
  - G2: coverage 103 against 108, where −2 is allowed;
  - G3a: 57 of 72 picture questions marked, against a bar of 85%.
- **It did work on its target.**
  - Five of the six cases are no longer wrong.
  - Risk falls from 11/126 to 7/121.
- **But it marks too much.** Five correct answers were lost on questions that mention a
  picture but are answered by words: a drawing's labels, a graphic's caption, alt text.
  The question alone does not show that difference.
- **Mechanism 3 (lists) is not changed.**
  - Only one of its three cases joined lists across sources.
  - The other two are substitution, mechanism 2, which is an accepted limit.

## Consequences

- **The system stays as E9 ran it.** Its prompt hash is unchanged (`c420fcf4…`).
  Mechanism 1 is an accepted limit: the user guide and the proposed five-type scope keep
  away from "what does it look like" questions.
- **A later attempt needs the distinction in the data, not only in the question.**
  Whether a picture's words answer the part is a reading change, and retrieval is frozen
  until deployment.
- **One prompt change moves about 2–3 cases each way** (c027, c033, c126, c207). Gates
  comparing two runs must allow that much noise.
- **v6q008 fails the answer schema in both runs.** It is reproducible: a defect to
  diagnose separately.

# S2. Does the whole site with its PDFs answer as well as today's index?

Design and gate written on 29 September 2026, before any answer was asked of the
candidate (PLAN §0f, Phase 3, slice S2).

## Question

The live index (version 4) holds 68 pages of the site in 315 passages. The candidate
(version 11) holds every cached page of the site (160) and every Lime Green PDF (98),
read as X8 selected (Docling with GLM-OCR table structure, only what the page shows,
D86–D87) and cut into passages as X9 selected (page-sized, tables inline): 1,845
passages. Quotes now match across the page's typography and Docling's superscript
spacing (X9 report, "Follow-up: quote matching"). Does the candidate answer the keyed
questions at least as well, never show a price, refer every emergency, and hold the
evidence for enough of conv-v1's follow-ups to run X36?

## Design

- **Arms,** in one session, on the same model servers and the same code:
  - `live`: version 4, served with `LIMESPEC_INDEX_VERSION=4`;
  - `candidate`: version 11, served with `LIMESPEC_INDEX_VERSION=11`.
- **Questions:** every question of frozen90 (90), held-out v2 (60) and held-out v3 (75),
  asked through the v1 API with `python -m evaluation ask`, `live` first.
- **Paired analysis,** as in X2 and X16: where both arms show the same answer they score
  the same; differing answers are graded blind (pairs shuffled with seed 11, arms
  hidden), then unblinded; differences are summed per case and cases resampled.
- **conv-v1 coverage:** a later turn (not a conversation's first) whose expected status
  is `answered` is covered when every one of its evidence quotes is found by
  `verify.find_quote` in a passage of the candidate from that quote's source (a page, or
  a PDF by its file). Quotes from images are not covered (no image index yet).

## Gate (fixed before the runs)

1. **No price shown:** no `candidate` answer shows a currency amount anywhere the reader
   sees it (`python -m evaluation guardrails`), across all 225 questions.
2. **Safety:** `candidate` gives the fixed safety referral to every emergency question.
3. **Status:** per set, `candidate` matches the key's expected status on at least as many
   questions as `live`, minus 3.
4. **Quality:** per set, over the graded pairs, `candidate` has at most 3 fewer sound
   answers and at most 3 more wrong ones than `live` (the grader's drift, X0).
5. **Coverage:** at least 30 answerable conv-v1 follow-ups are covered (the bar X36 was
   registered with, D77).

Reported, not gated: answers that differ, per set; coverage per conv-v1 source format;
the readings' flagged pages; seconds per answer.

A pass makes version 11 live, and X36 runs on it. A failure is diagnosed before any
change; version 4 stays live meanwhile.

## Grading

Blind, by an LLM, on the anonymised pairs; the arm mapping is read only after every
verdict is saved. The scale is v3's: **sound** answers every part correctly (or gives the
refusal or referral the key expects) and says nothing the key forbids; **partial** is
correct but misses a part; **wrong** states something incorrect or forbidden, or has the
wrong status.

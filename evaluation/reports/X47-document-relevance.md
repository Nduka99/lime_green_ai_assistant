# X47. Which documents earn their place in retrieval?

Rules written on 2 October 2026 before any run. The user asked for the audit after X45
(the corpus had never been checked for relevance, and documents that rarely help can
crowd out the ones that do).

## What was measured first (version 26, the four older sets' replays)

| Group | Docs | Passages | Share of retrieved slots | Passages holding key evidence | Docs with none |
|---|---|---|---|---|---|
| Product pages | 43 | 114 | 24.8% | 125 | 5 |
| Technical sheets | 35 | 164 | 19.7% | 66 | 18 |
| Guides and brochures | 12 | 407 | 13.3% | 82 | 0 |
| Company and other pages | 14 | 107 | 9.1% | 35 | 1 |
| Case studies | 26 | 179 | 6.7% | 28 | 10 |
| Knowledge-base pages | 18 | 112 | 5.4% | 20 | 8 |
| News | 24 | 109 | 4.8% | 13 | 16 |
| Colour pages | 30 | 55 | 4.3% | 144 | 3 |
| Safety data sheets | 33 | 548 | 3.7% | 238 | 2 |
| EPD and carbon reports | 5 | 73 | 2.5% | 0 | 5 |
| GOV.UK guidance | 2 | 333 | 1.8% | 0 | 2 |
| Inspirations | 5 | 88 | 1.3% | 2 | 3 |

**Two candidates are ruled out by measurement:**
- **2014 technical sheets.** Each is the only technical sheet for its product (Ashlar,
  Finish WP, Natural Finish, Pure Lime Grout, Stipple Coat, Tradirend, Ultra). They are
  not superseded.
- **Safety data sheets.** They cannot be de-duplicated. Each sheet is evidence about its
  own product, so keeping one copy of shared text would cite the wrong product (X44).
  Scoped search already handles look-alike sheets.

GOV.UK guidance stays by the user's choice (X44). Its passages are in their own channel
and never take a company place.

## Arms (each a build from the base version's flags, leaving one group out)

- **N:** news pages (`/news/`).
- **C:** case studies (`/support/case-studies/`).
- **I:** inspiration pages (`/inspirations/`).
- **P:** EPD and carbon reports.

A page left out also takes its pictures with it.

## What each arm reports

- The four replays, `kb-probe` text and pictures, `web-facts`, `image-facts`, and search
  p95.
- What the group alone holds: `web-facts` facts and `kb-probe` questions on its pages,
  and the v6 cases planned on its sources (counted from the plan, never the key: news
  12, case studies 13, inspirations 2 of 220).

## Rule

- **A group becomes a removal candidate only if both hold:**
  - leaving it out loses no replay part beyond 1 per set and no `kb-probe` question,
    except questions about the group's own pages;
  - something improves beyond noise: replay parts summed over the four sets up by 3 or
    more, or search p95 down by 0.1 s or more.
- **The user decides removals.** Leaving a group out is a decision about what the
  assistant answers from. Every candidate is listed with what it holds alone, including
  the v6 cases it would leave unanswerable.
- The base is version 28 if X46 adopts it, otherwise version 26.

## The data-type ladder (added 2 October, before any ladder run)

X43 added the new web reader, Word files, GOV.UK guidance and pictures in one build,
and later rounds judged arms against baselines that still held other changes (E4 was
judged against a build with E2's repetition). The cross-check that should have come
first is one change per build from the last known-good index, version 17. Each step
adds one thing to the step before:

| Step | Build | Adds |
|---|---|---|
| L0 | version 17 (exists) | the pre-multimodal reference |
| L1 | new web reader + PDFs, `--leave-out .docx --leave-out gov.uk`, no pictures | X42–X46 web reading (E1, E2, R1, F3a) |
| L2 | L1 without leaving out `.docx` | Word declarations |
| L3 | L2 without leaving out `gov.uk` | GOV.UK guidance (own channel) |
| L4 | L3 with `--images` (= version 29) | pictures (own channel) |
| L5 | L4 with `--compiled-descriptions` (= version 28) | E4 |

- **Measured at each step:** the four replays with `--channels`, `web-facts`,
  `kb-probe` by stratum, and search p95 (scratch `g7.py`).
- **Rule:** a step is kept only if no replay set falls by more than 1 part against
  the step before, and the step raises its own strata in `kb-probe` (or, for L1, the
  replays or `web-facts`).
- A step that fails is reported with the parts it loses. The decision to drop a data
  type goes to the user.

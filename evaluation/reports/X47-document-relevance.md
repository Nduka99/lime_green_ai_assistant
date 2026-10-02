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

## Ladder result (2 October, 06:50–09:25)

Builds: L1 = version 30, L2 = 31, L3 = 32; L4 and L5 are versions 29 and 28, measured
again. Runs in `data/runs/x47/L0..L5/`; log `data/runs/x47/ladder.log`. Replays are parts
reached; `kb-probe` columns are questions found.

| Step | frozen90 | v2 | v3 | v4 | Sum | web-facts | word | guidance | pictures (3 strata) | listing | other text | p95 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L0 v17 | 103 | 83 | 76 | 119 | 381 | 0.921 | 0/6 | 0/6 | 0/20 | 6/6 | 20/26 | 1.41 |
| L1 web reader | 108 | 82 | 77 | 118 | 385 | 0.969 | 0/6 | 0/6 | 0/20 | 6/6 | 22/26 | 1.67 |
| L2 + Word | 108 | 82 | 77 | 118 | 385 | 0.969 | 4/6 | 0/6 | 0/20 | 6/6 | 22/26 | 1.25 |
| L3 + GOV.UK | 107 | 85 | 77 | 118 | 387 | 0.966 | 4/6 | 6/6 | 0/20 | 6/6 | 22/26 | 1.89 |
| L4 + pictures | 107 | 81 | 77 | 118 | 383 | 0.966 | 4/6 | 6/6 | 14/20 | 6/6 | 22/26 | 1.35 |
| L5 + E4 | 111 | 80 | 88 | 121 | 400 | 0.952 | 4/6 | 6/6 | 14/20 | 6/6 | 22/26 | 1.34 |

"Other text" is web content, PDF text and tables, and cross-type. L4 and L5 reproduce
versions 29 and 28's earlier replays exactly.

**The rule, step by step.**

| Step | Replay change against the step before | Own measure | Verdict as registered |
|---|---|---|---|
| L1 | +5, −1, +1, −1 | replays 381 → 385; `web-facts` 0.921 → 0.969 | **Kept** |
| L2 | 0, 0, 0, 0 | `word` 0 → 4 of 6 | **Kept** |
| L3 | −1, +3, 0, 0 | `guidance` 0 → 6 of 6 | **Kept** |
| L4 | 0, **−4**, 0, 0 | pictures 0 → 14 of 20 | **Fails**: v2 falls by 4 |
| L5 | +4, −1, +11, +3 | `listing` already 6 of 6 at L4 | **Fails**: its stratum cannot rise |

- **L4's failure is not the pictures' content.**
  - Pictures took no company place: each search's 8 company passages come first and the
    pictures follow them.
  - The 4 parts belong to one case (c06, Warmshell Internal), covered below.
- **L5's failure is the rule's wording, not a loss.**
  - `listing` was at its ceiling before E4, so no step could raise it.
  - E4's own evidence is the replays: +17 parts summed, and v2 −1. That passes X45's E4
    rule (summed parts rise, no set falls by more than 1). It costs `web-facts` 5 facts
    (0.966 → 0.952), as X45 found.
- **Search time is noise at this resolution.** One run of 60 searches ranges from 1.25 to
  1.89 s with no order: L4 adds a channel and measures faster than L3. Version 28
  passes G7 again (1.34 s, bar 1.5 s).

**Where v2's two parts went (83 at version 17, 81 at version 29).**

| Step | v2 | Case c06 (30 parts) | c06's About-page parts (10) | Other cases (110 parts) |
|---|---|---|---|---|
| L0 | 83 | 24 | 10 | 59 |
| L1 | 82 | 17 | 6 | 65 |
| L2 | 82 | 17 | 6 | 65 |
| L3 | 85 | 19 | 8 | 66 |
| L4 | 81 | 15 | 4 | 66 |
| L5 | 80 | 17 | 6 | 63 |

- **Every loss is in one case.** Case c06 asks about Warmshell Internal in 5 wordings of
  6 parts. Two of its parts (the "third-party BDA Agrément" and the "25-year materials
  warranty") are stated only on the About Lime Green page.
- **L1, the web reader: c06 −7, other cases +6.**
  - In page form, those two facts sit inside a 1,331-character section headed by a
    co-founder's introduction. Version 17 held them in a 668-character passage headed "We
    are the only company to offer a complete solution for wood fibre insulation", which
    ranked higher.
  - Elsewhere the reader gains 6 parts.
- **L3 and L4: the same passage crosses the company's 8th place.**
  - The company passages changed. No guidance passage reached these questions, and the
    pictures given at L4 followed the 8 company places without taking one.
  - The About passage entered the company's top 8 at L3 (+2 in c06, and one more part in
    c01 from another passage) and left it at L4 (−4).
  - The cause is the keyword index. Each version has one BM25 index over all its
    passages, so its word statistics (document frequencies, average length) include
    guidance and picture passages. Adding a channel changes the company's keyword
    scores, although ranking keeps the channels apart (ADR 0030).
  - Vector search is unaffected: it scans each channel exactly.
- **L5, E4: other cases −3** (v2q009's sample terms, as X45 found).
- **So v2's two parts:** one is the web reader's net change, concentrated in c06's
  About-page facts. The other is that same passage moving with the shared word
  statistics. No data type removes v2 evidence by its content.

**Not decided here (the user's decision):**
- whether pictures (L4) and E4 (L5) stay, given the rule's verdicts above;
- whether to register a structural fix for the shared word statistics: a BM25 index per
  channel, so that adding guidance or pictures cannot move company results. That is
  ADR 0030's separation carried into the keyword index. Its rule would be written before
  any build: company results identical to a version built without the other channels,
  replays measured.

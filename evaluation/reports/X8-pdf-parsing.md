# X8. Does Docling read Lime Green's PDFs accurately enough to index?

Design and gate written on 28 September 2026, before the ground truth was written and
before either parser ran on these pages.

## Question

The plain PDF text layer (pypdf, used so far) flattens tables: a Declaration of
Performance's mix table comes out as `Cement Lime Sand 1 0.25 3 1 0.5 4.5 1 1 6 1 2 9`,
losing which ratio belongs to which mortar class (PLAN §0f). Docling's standard pipeline
reads the PDF's own characters and rebuilds tables from them
([Docling report](https://arxiv.org/html/2408.09869v4)). Before its output becomes the
index's text, is it accurate on these documents: tables whose cells keep their row and
column, no text lost, and sentences read in order across columns?

## Pages

Twenty born-digital pages of Lime Green's own PDFs, chosen by code before either parser
ran on them: per format, documents in a seeded shuffle (seed 8) of the catalogue, taking
the first page with a text layer for declarations and datasheets and a seeded random
page with a text layer otherwise. One rule was added before any scoring: a page whose
parser output had already been seen (the UK Declaration of Performance for Coloured
Cement Mortars, probed in S0) is replaced by the next document in the same order.

| Format | Page | Document |
|---|---|---|
| Declaration | 1 | EU Declaration of Performance Coloured Cement Mortars |
| Declaration | 1 | EU declaration of performance, Warmshell Meshcoat |
| Declaration | 1 | UKCA declaration of conformity, Warmshell Meshcoat |
| Declaration | 1 | EPD, Hemp Binder |
| Declaration | 1 | UK Declaration of Performance, Duro |
| Datasheet | 1 | Hemp Binder TDS |
| Datasheet | 1 | Solo Primer TDS |
| Datasheet | 1 | Pure Lime Grout |
| Datasheet | 1 | Warmshell Aerogel Insulation Board |
| Datasheet | 1 | Tradirend |
| Safety data sheet | 6 | Roman Stucco Finish |
| Safety data sheet | 9 | Hand-cast Hemp Binder |
| Safety data sheet | 5 | Silic8 AD2 |
| Guide | 2 | Warmshell roof design guide and installation details v2 |
| Guide | 11 | IWI Architect Reference |
| Guide | 6 | Warmshell Internal IWI site assessment checklist |
| Guide | 8 | Design Guide IWI |
| Guide | 10 | Installation Guide IWI |
| Policy | 2 | Internal Warmshell Warranty 2022 |
| Certificate | 1 | ISO 14001 certificate |

The 18 pages with no text layer (mostly installation drawings) are outside this run:
transcribing them needs a VLM on the GPU and is measured separately, labelled as
transcription.

## Ground truth

Written from each page's image, before either parser runs, and registered as the set
`x8-pages` (hashed like every key):

- **tables:** every table as a grid, its header row first;
- **sentences:** up to five sentences per page copied from the image, preferring ones
  that cross a line break or sit in a multi-column layout.

## Arms

- `pypdf`: the text layer, as indexed so far;
- `docling`: `limespec`'s own Docling path (standard pipeline, OCR off, TableFormer in
  accurate mode) producing the element model the index will read (PLAN §0f).

## Measures

1. **Table cells:** each truth table cell becomes a triple (the row's first cell, its
   column's header, the value). A triple counts as found when a parsed table on that page
   has a row whose label contains the truth row label, under a column whose header
   contains the truth column label, with the same value, all compared with whitespace
   removed and case ignored. Only `docling` produces tables; the text layer has no rows
   or columns to score.
2. **Text kept:** the share of the page's text-layer words that appear in the parser's
   text for that page (counted as a multiset).
3. **Sentences whole:** the share of truth sentences found as continuous text in the
   parser's page text (whitespace and case ignored).
4. **Table numbers:** the share of numbers in truth tables that appear in the parser's
   page text.

Also reported: seconds per page and peak memory.

## Gate (fixed before the run)

Docling becomes the parser for born-digital pages if, pooled over the twenty pages:

1. table cells ≥ 0.95, with no table below 0.80 left undiagnosed;
2. text kept ≥ 0.99;
3. sentences whole ≥ 0.95, and not below `pypdf`;
4. table numbers ≥ 0.99.

A failure is diagnosed before any change (for example a Docling option, or keeping the
text layer beside the tables for one format).

## Amendment before the run (28 September 2026)

Written while recording the ground truth, before either parser ran on these pages.
Some declarations list their performance as a borderless two-column layout ("Reaction
to fire: … Class A1") rather than a ruled table. Measure 1 counts only parsed tables, so
it would penalise a parser that keeps each label and value together as text, which is
as usable for answering. The truth therefore records such layouts as **pairs**
(label, value), with a fifth measure:

5. **Pairs kept:** the share of truth pairs whose label and value appear together in one
   parsed table row or one parsed text element (for the text layer, one line), compared
   with whitespace removed and case ignored.

Gate 1 now reads: table cells ≥ 0.95 and pairs kept ≥ 0.95, with no table below 0.80
left undiagnosed. Nothing else changes.

**Second amendment, also before the run.** Safety data sheets put each label on one line
and its value on the next ("pH", then "11.2"), so their relation depends on reading
order. A pair also counts as kept when its value is in the parsed element that directly
follows the label's element (for the text layer, the next line).

**Clarifications to the scoring, before the run,** found by the scorer's own tests on
invented pages: a parsed column header joins the header rows above it ("Performance
Class i"), so it must *end with* the truth header rather than contain it ("Class i" is
contained in "Class ii"; this is stricter than registered and can only lower Docling's
score); and words are compared without punctuation at their edges, on both sides alike,
because a rebuilt table row adds separators ("A1;").

**Fix before any score, recorded here:** the first run stopped on the contents page
(guide, page 2), which Docling returns as a table labelled `document_index`, not
`table`. The reader now reads every item by what it carries (table rows, a figure's
caption, text, or a key-value region's text cells), tested on invented items of each
kind (`264784e` + this commit). No score had been computed.

## Result, round 1: fail

Run on 28 September 2026 (`6846a81`), outputs in `data/runs/x8-pages/` (both parsers'
text per page and every measure per page). Peak memory 1,185 MB; Docling 1.1 s per page
(median), 18.7 s for the first page, which loads the models.

| Measure | pypdf | docling | Gate |
|---|---|---|---|
| Table cells | — | 0.779 | ≥ 0.95 |
| Pairs kept | 0.761 | 0.957 | ≥ 0.95 |
| Text kept | 1.000 | 0.976 | ≥ 0.99 |
| Sentences whole | 0.989 | 0.924 | ≥ 0.95, and ≥ pypdf |
| Table numbers | 1.000 | 1.000 | ≥ 0.99 |
| Lowest table | — | 0.000 | ≥ 0.80 |

Gates 1, 2 and 3 fail; Docling is not adopted on this result.

**Diagnosis,** from both parsers' saved output, page by page:

| Cause | Pages | Owner |
|---|---|---|
| The U-value table was read perfectly (every value under its thickness column), but a spanning "U Value W / m²K" subheader is joined after the column name, so the pre-run "ends with" clarification failed all 12 cells | 17 | scorer |
| List numbering ("5.", "a.", "ii.", "9.1.") is dropped: the reader used Docling's `text`, which strips markers; `orig` keeps them | 1, 5, 13, 19 | reader |
| Table header text disappears when its cells are empty (a checklist's heading over tick boxes) or when it heads the label column ("Essential Characteristics") | 1, 16 | reader |
| Docling's PDF parser sanitises typography by default (curly quotes and apostrophes to straight, en dash to hyphen; `do_sanitization`, not exposed by Docling's options), so sentences copied from the page image no longer match character for character | 1, 8, 9, 11, 18 | matching |
| Letter-spaced titles, superscripts read as "m 2" and web addresses split at a line-end hyphen count as lost words though the text is there | 1, 20 | scorer |
| Styled header rows (white on green) are not recognised as headers: every row keeps its label and value, but values have no column name | 8 | Docling |

Only the last is a limit of Docling itself; the others are in this project's reader or
scoring. Fixes follow as general changes (read `orig`; keep a table's header row as its
own element; compare header components; fold typographic variants on both sides of
every comparison), and are then checked on a **new** sample of pages they were not
derived from (round 2), with its gate written first.

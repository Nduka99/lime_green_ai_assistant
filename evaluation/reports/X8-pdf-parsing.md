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

## After round 1: fixes, an exploratory re-score, and the table-model question

**General fixes** (`9af80e3`, `5a26d78`): the reader takes Docling's `orig` text (list
and section numbering kept); each table's header row is its own element (header text
kept over empty cells); header levels are joined by " › " and the scorer matches a truth
header against those levels; every quote mark and dash is folded alike on both sides
(Docling's parser writes typography plainly); and after each page, any text-layer line
with a word found nowhere in Docling's text is added back as a `recovered` element, so
no text is lost.

**Exploratory re-score of round 1's pages** (the fixes were derived from them, so this is
not the gate): table cells 0.919, pairs 0.957, text kept 0.990, sentences 0.989 (the
text layer 0.989), table numbers 1.000; the lowest table is still 0.000. What remains
is one limit of Docling's table model: header rows styled as white text on a coloured
band (the 2014 datasheets' green bars) are not recognised as headers. Every such row
keeps its label and value together; only the column names are missing.

**Alternatives researched for that limit:**

| Option | Evidence | Verdict |
|---|---|---|
| TableFormer V2 (`TableStructureV2Options`, `docling-project/TableFormerV2`) | 52.4M parameters, 210 MB; the model page has no model card and no stated licence; an open issue (5 June 2026) reports it duplicating rows in multi-page tables, ~7k to ~42k words ([#3553](https://github.com/docling-project/docling/issues/3553)) | Out: no licence to check, and a known defect |
| Granite Vision 4.1 4B (`GraniteVisionTableStructureOptions`) | A 4B vision-language model generating the table's text ([catalog](https://docling-project.github.io/docling/usage/model_catalog/)); the GPU is full, so it would run on the CPU | Out for now: too heavy here, and generated text breaks quoting |
| Treat a table's first row as its header when none is flagged | Would mislabel headerless key-value tables and contents pages (their first row is data) | Rejected: wrong for a whole class of tables |

Docling's default model (TableFormer, accurate) stays. Round 2 runs on new pages, with
the same measures and gate, as registered.

## Round 2: design and gate

Written on 28 September 2026, before round 2's pages were drawn, before their truth was
written, and before any VLM read a Lime Green page.

**Question.** On pages that none of round 1's fixes came from, does Docling now pass?
And does re-reading each table's structure with a small open-weight VLM do better? The
VLMs lead OmniDocBench on tables (PLAN §0f) but write their own text, so here they give
structure only.

**Pages.** Twenty, drawn by `python -m evaluation sample-pages --seed 9 --exclude-set
x8-pages` (`evaluation/pages.py`), with round 1's quotas and rules. The same code with
seed 8 reproduces round 1's twenty pages exactly. A page has a text layer when it holds at
least 10 words, the rule that reproduces round 1's choices. Also left out:

- every document used in round 1;
- the UK Declaration of Performance for Coloured Cement Mortars, probed in S0;
- any page whose words resemble a round-1 page or an earlier round-2 page (Jaccard ≥ 0.8
  over word sets), such as the UK and EU declarations of one product, or a safety data
  sheet's shared boilerplate.

Only four guides are unused, so the fifth guide page is a further page of one of them, in
the same seeded order. The Kiwa BDA Agrément (AES-encrypted, about 11 pages) cannot be read
by pypdf and is outside the sample. Whether Docling reads it is checked in S2's validation.

**Arms.**

- `pypdf`: the text layer, the reference for sentences.
- `docling`: as after round 1 (`9af80e3`, `5a26d78`).
- `glm-ocr` and `paddleocr-vl`: Docling as above, except that each table Docling finds is
  read again by a VLM:
  1. the table's box is cropped from the page rendered at 200 DPI (GLM-OCR's setting for
     PDFs) and sent to llama-server with `Table Recognition:` and the model's published
     settings. For GLM-OCR these are temperature 0, top-k 1, repetition penalty 1.1 and at
     most 8192 tokens ([config](https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml)).
     For PaddleOCR-VL they are temperature 0 and at most 8192 tokens
     ([card](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF));
  2. the answer is read as a grid with spans. GLM-OCR writes HTML; PaddleOCR-VL writes OTSL
     with six tags and marks no header cells;
  3. the VLM supplies structure only. After folding case, typography and Unicode
     compatibility forms on both sides, each cell's text must be spelt by words of the PDF
     inside the table's box (Docling's parsed word cells), each word used once. The cell's
     text is then those PDF words, so every quote stays the document's own characters. A
     cell that cannot be spelt this way is dropped from its row, never quotable, and counted;
  4. header rows are the rows the VLM marks as headers (`<th>`, `<thead>`). If it marks
     none, a row is a header when its words equal those of a row Docling flagged as one;
  5. if the answer does not read as a table, Docling's table stands.

  Models: GLM-OCR f16 with its Q8_0 projector
  ([ggml-org/GLM-OCR-GGUF](https://huggingface.co/ggml-org/GLM-OCR-GGUF); weights MIT) and
  PaddleOCR-VL-1.6 in BF16
  ([PaddlePaddle/PaddleOCR-VL-1.6-GGUF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF);
  Apache-2.0). They run on the installed llama.cpp b10298, which has both architectures,
  one model on the GPU at a time with the generator stopped. Settings not published by the
  models (the crop margin, image size limits) are fixed while developing on round 1's
  pages only, and frozen at a commit named here before the round-2 run.

**Measures and gate,** for each arm, as in round 1 with its amendments and clarified
scoring:

1. table cells ≥ 0.95 and pairs kept ≥ 0.95, with no table below 0.80 left undiagnosed;
2. text kept ≥ 0.99;
3. sentences whole ≥ 0.95, and not below `pypdf`;
4. table numbers ≥ 0.99.

Also reported for each arm: cells dropped because they could not be spelt, seconds per
page (mean and median), peak RAM (the reading process plus the VLM server), peak VRAM, and
the hours projected for Lime Green's 573 readable PDF pages (mean seconds per page × 573).

**Selection, fixed now.** Among the arms that pass every gate item, the highest
table-cell score wins. Scores within 0.01 of each other count as a tie, won by the lower
peak memory (RAM plus VRAM), then by the faster arm. If no arm passes, the failures are
diagnosed and the decision goes to the user.

**Transcription check.** Measured on Lime Green's PDFs today:

- 2 pages have an empty text layer (pages 3 and 4 of the Aerogel Insulation Board
  datasheet, both drawings);
- 8 pages hold fewer than 10 words: those 2, four first pages (probably covers), and
  2 other pages.

The text layer does not reproduce the "18 pages without a text layer" in PLAN §0f, so
that figure is corrected. All 8 pages are checked (`--blank 8`). The truth is every legible word on the
rendered page, written before any model runs. Each model transcribes the whole page
(GLM-OCR with `Text Recognition:`, PaddleOCR-VL with `OCR:`). Word recall and precision are
counted against the truth as multisets, folded as above. A model's transcriptions may be
indexed as searchable text labelled "transcribed", and never quotable, only if recall is
≥ 0.90 and precision ≥ 0.95, pooled over the 8 pages. If the table winner's model passes,
it is preferred, so that one model serves both.

**Truth sealed** (28 September 2026, set `x8-pages-r2`, 29 files hashed), before any parser
or model read these pages:

- the 20 pages hold 5 tables with 64 cells, 77 pairs and 93 sentences;
- the 8 low-text pages hold 106 words;
- 42 of the 64 cells come from one template, the system-boundary table with rotated labels,
  which appears on two carbon-footprint documents (pages 2 and 3). Cell scores are therefore
  also reported table by table.

Each page was rendered at 144 DPI in its own process. The IWI Installation Guide makes
Docling's PDF parser crash natively (Windows heap corruption, 0xc0000374) when it is the
first document a process converts. This happened in every configuration tried: without page
images, at 72 and 200 DPI, and with one parser thread. Converting another document first
avoided it in every trial. Its two pages (b2, b4) were therefore rendered after another
document, which leaves the image unchanged. The crash is an ingestion risk and is researched
separately.

For the blank pages, "every legible word" includes wordmarks ("lime green", "warm shell") and
the printed text in photographs. It excludes signatures and symbols (| © ®), and the scoring
counts only tokens that hold a letter or a digit.

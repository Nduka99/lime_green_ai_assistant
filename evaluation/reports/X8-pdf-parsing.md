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

**Development on round 1's pages, and amendments before the round-2 run** (28 September
2026). Both models ran on llama.cpp b10298 on 127.0.0.1:8083, with the platform's key
(requests without it get 401) and the generator stopped. Their raw answers on round 1's
tables showed:

- **Structure:** both models read spans correctly, for example the two-level
  "Performance › Class i" header, the rowspan-7 "EN998-2 2016" and separate title rows.
- **Text:** both write their own text. GLM-OCR drops spaces ("10.253" for "1 0.25 3");
  PaddleOCR-VL "corrects" the PDF's ",0.5%" to "0.5%". Spelling each cell from the PDF's
  words restores the document's text or drops the cell, as designed.
- **Headers:** neither model marks header cells. GLM-OCR's HTML has no `<th>` or `<thead>`,
  as PaddleOCR-VL's OTSL was known to have none. Both VLM arms therefore take header rows
  from Docling's flags.

Changes that are general, derived only from round 1's pages, and made before any model read
a round-2 page:

1. **Header rows from Docling's flags.** Docling and the model can split a header
   differently: "Essential Characteristics" spans two header rows in the model's reading
   and sits in the second row in Docling's. "Equal to a row Docling flagged" therefore never
   matched. A row is now a header when all its words are among the words of the rows Docling
   flagged.
2. **Spanning values.** A value spanning columns applies to each column it spans, so it is
   repeated, as a spanning header already was. Written once, the value lost which classes it
   applies to ("See SDS" across Class i–iv). A value spanning the table's whole width is a
   title and is written once.
3. **No lost words.** The PDF's words inside a table's box that no cell used are kept as one
   `recovered` element after the table: tick boxes the model drew as ☐, and a value the
   model left out. Previously the text-layer check restored such a line only when one of its
   words appeared nowhere else on the page.
4. **The models' notation.** Inline LaTeX in a cell ($\lambda$, `\(m^{2}\)`) becomes the
   characters a PDF prints (λ, m2) before spelling, using pylatexenc 2.11 (MIT, 134 KB, no
   dependencies; user approved). Only math spans are converted, because outside math `%` and
   `&` are ordinary characters. PaddleOCR-VL writes a line break inside an OTSL cell as the
   two characters `\n`, which is read as a space.

Settings fixed now: the crop is exactly Docling's table box (no margin; every round-1 table
read whole); image size limits are each projector's defaults.

Exploratory scores on round 1's pages, which the changes came from, so not a gate:

| Measure | docling | glm-ocr | paddleocr-vl |
|---|---|---|---|
| Table cells | 0.919 | 0.919 | 0.919 |
| Pairs kept | 0.957 | 0.935 | 0.957 |
| Text kept | 0.990 | 0.990 | 0.990 |
| Sentences whole | 0.989 | 0.989 | 0.989 |
| Cells left unspelt | — | 6 of 280 | 7 of 261 |

GLM-OCR's lost pair is its own omission (a contents page's "31" is in no cell). The unspelt
cells are the six tick boxes, plus PaddleOCR-VL's ",0.5%". On these pages neither VLM arm
improves on Docling alone, and the styled-header tables still score 0. Round 2 decides.

**Code frozen for the round-2 run at `9d9eb35`.**

## Result, round 2: every arm fails

Run on 28 September 2026 at `62be340`, which has the same code as `9d9eb35`. Outputs are
in `data/runs/x8-r2/<arm>/` (parsed elements, scores, and memory sampled every second).

| Measure | pypdf | docling | glm-ocr | paddleocr-vl | Gate |
|---|---|---|---|---|---|
| Table cells | — | 0.047 | 0.016 | 0.016 | ≥ 0.95 |
| Pairs kept | 0.571 | 0.610 | 0.610 | 0.610 | ≥ 0.95 |
| Text kept | 1.000 | 0.995 | 0.995 | 0.995 | ≥ 0.99 |
| Sentences whole | 1.000 | 0.957 | 0.957 | 0.957 | ≥ 0.95 and ≥ pypdf |
| Table numbers | 1.000 | 1.000 | 1.000 | 1.000 | ≥ 0.99 |
| Lowest table | — | 0.000 | 0.000 | 0.000 | ≥ 0.80 |
| Cells unspelt | — | — | 110 of 204 | 111 of 219 | reported |
| Seconds per page, mean (median) | — | 2.6 (1.3) | 3.8 (1.3) | 3.5 (1.3) | reported |
| Hours for 573 pages | — | 0.4 | 0.6 | 0.6 | reported |
| Peak RAM: reader + model server | — | 1.1 GB | 1.3 + 4.2 GB | 1.3 + 1.5 GB | reported |
| Peak VRAM of the model | — | 0 | 3.9 GB | 2.3 GB | reported |

Transcription check, over the 8 low-text pages: GLM-OCR had recall 0.769 and precision 0.952;
PaddleOCR-VL had recall 0.865 and precision 0.928. Both fail the bar (recall ≥ 0.90 and
precision ≥ 0.95). PaddleOCR-VL's first attempt ended without output: the known native Docling
crash, since rendering reaches the IWI guide. The re-run completed.

No arm passes, so by the selection rule the decision goes to the user after this diagnosis.

**Diagnosis,** page by page, from the saved outputs:

| Cause | Pages (cells) | Arms | Owner |
|---|---|---|---|
| Header rows not recognised. Docling flags only the top row of the two-level system-boundary tables (stage names over module codes), and no row of the ruled mix-designation table. Neither VLM marks header cells, and both take Docling's flags, so values lose their column names. | 1, 2, 3, 10 (61 of 64) | all | Docling's TableFormer; the VLMs give no header marks |
| Docling's PDF parser drops glyphs in the One Click LCA reports' font: every "u" and "f" is missing ("Man fact rer", "GWP- ossil", "M ch Wenlock"), while pypdf reads them. Sentences on page 1: 1 of 5. The VLM arms spell from the same words, so they inherit it. | 1 (sentences, pairs) | all | docling-parse 7.22.0 |
| Rotated column labels (the system-boundary table's names row) | 2, 3 | all | structure |
| The VLMs split a row with multi-line cells into sub-rows, pairing "EC No." with "Eye Irrit. 2" | 11 | glm-ocr, paddleocr-vl | the models |
| Unspelt cells are mostly the rotated labels and the glyph-dropped words above | 1, 2, 3 | glm-ocr, paddleocr-vl | inherited |
| Measurement: truth written "CO2e" where the PDF has "CO₂e" (subscript two); the scorer folds typography but not compatibility forms. SDS pairs whose label includes its section number ("6.1. …") are missed by the text layer too. | 1–3, 13 (pairs) | all, including pypdf | truth and scorer |

What round 2 establishes:

1. **The bottleneck is recognising header rows, not reading cells.** Every VLM read the
   cells' structure correctly where Docling did, but neither model marks headers, so the
   hybrid cannot fix it as designed.
2. **Docling's text is not always the PDF's own characters.** On one font family it loses
   letters that the text layer keeps, which contradicts the premise in §0f that Docling
   reads the PDF's own characters.
3. **Memory and speed would allow either VLM** (under 4 GB of VRAM, at most 0.6 h for the
   corpus). Quality rules them out.

## Round 3: whole tables (design and gate)

Written on 28 September 2026, after round 2 and before round 3's pages were drawn. The
design was chosen by the user from round 2's diagnosis.

**Question.** Row-by-row passages need each value's column name, so they depend on
recognising header rows, which round 2 showed to be the parsers' weak point. A table kept
whole (every row, header rows included, in its grid) carries its column names with its
values, with no header decision to make. How to write such a passage for the answering
model is experiment X9's question (formats measurably change LLM table reading; [Table
Meets LLM](https://arxiv.org/html/2305.13062v4), [TQA-Bench](https://arxiv.org/pdf/2411.19504)).
Round 3 asks the parser's part: does each parser put every table value in its right row and
column?

**Pages.** `python -m evaluation page-candidates --seed 10 --exclude-set x8-pages
--exclude-set x8-pages-r2` lists candidates (`evaluation/pages.py`): every Lime Green PDF
page with a text layer, in a seeded order. It leaves out pages used in rounds 1 and 2, any
page resembling an earlier one (Jaccard ≥ 0.8), and more than two pages per document.
Candidates are rendered in that order and judged from the image alone, before any parser
reads them, as showing a table or not. A table here means cells in at least two rows and two
columns, set in a grid whether ruled or only aligned; a list of labels, each followed by one
value, counts only when it is laid out as such a grid. The first 20 pages that show a table
form the sample. Every judged candidate and its judgement are kept with the set.

**Truth.** Every table on the page is written as a full grid:

- all rows, with the number of header rows recorded;
- each spanning cell repeated in every position it covers;
- text as printed, with sub- and superscripts as plain digits.

Pairs and up to five sentences are recorded as before (reported, not gated).

**Arms.** `docling`, `glm-ocr` and `paddleocr-vl` as in round 2, unchanged except that each
table is also emitted whole: Docling's grid, or the model's grid spelt in the PDF's words.
The code is frozen at the commit that registers this round.

**Measures and gate,** for each arm:

1. **Table values placed ≥ 0.95.** A truth value (a cell of a data row) is placed when a
   parsed table on its page has it in a row whose first cell contains the truth row's
   label, and in a column whose cell in some row above equals the truth column's header (its
   lowest header row). The comparison ignores case, whitespace, typographic variants and
   Unicode compatibility forms. Every table's share must be ≥ 0.80, or diagnosed.
2. **Text kept ≥ 0.99.**
3. **Table numbers ≥ 0.99.**

Also reported: round 1's header-dependent table cells, pairs, sentences, cells the VLMs could
not spell, seconds per page, peak RAM and VRAM, and hours for 573 pages.

**Selection:** as in round 2. Among passing arms the most values placed wins; within 0.01,
the lower peak memory, then the faster arm. If none passes, diagnose and bring the decision
to the user.

**Known limit, measured separately:** docling-parse drops two letters in the One Click LCA
font. Pages in that font count against every arm, as the text is what they read.

**Clarification before any page was selected** (28 September 2026, after judging candidates
1 and 2, before any parser read them). Candidate 2 (a safety data sheet's supplier details)
showed the definition was ambiguous: a list of labels, each with one value, is aligned in two
columns. Such lists have no header row and are measured by pairs in every round. The grid
measure targets tables with column headers, where round 2 failed. A table here therefore
needs a header row (or header column) over at least two data rows and two columns; key–value
lists do not count, whatever their alignment.

**Truth sealed** (28 September 2026, set `x8-pages-r3`, before any parser read these pages):

- 78 candidates were judged (`judged.json`, one yes/no each), and the first 20 showing a table
  form the sample: 22 tables and 367 values, 12 of them from safety data sheets;
- one wide EPD impact table (7 impacts × 18 modules) holds 133 values;
- four SDS transport tables of dashes hold 72;
- two 2014 datasheets carry the styled-header family that round 2 could not read.

Because of this mix, results are also reported table by table, and the lowest-table item
guards against any single table carrying the pooled score.

## Result, round 3: GLM-OCR passes and is selected

Run on 28 September 2026 at `409ed54`, with code unchanged since `439de2f`. Outputs are in
`data/runs/x8-r3/<arm>/`.

| Measure | pypdf | docling | glm-ocr | paddleocr-vl | Gate |
|---|---|---|---|---|---|
| Table values placed | — | 0.875 | **0.984** | 0.932 | ≥ 0.95 |
| Lowest table | — | 0.333 | **0.800** | 0.429 | ≥ 0.80 |
| Text kept | 1.000 | 0.996 | 0.996 | 0.996 | ≥ 0.99 |
| Table numbers | 1.000 | 1.000 | 1.000 | 1.000 | ≥ 0.99 |
| Cells, header-dependent (round 1's measure) | — | 0.782 | 0.891 | 0.845 | reported |
| Pairs / sentences | 0.759 / 0.988 | 0.621 / 0.988 | 0.621 / 0.988 | 0.621 / 0.988 | reported |
| Cells unspelt | — | — | 5 of 600 | 8 of 621 | reported |
| Seconds per page, mean (median) | — | 3.5 (2.2) | 7.1 (5.0) | 6.0 (4.1) | reported |
| Hours for 573 pages | — | 0.6 | 1.1 | 1.0 | reported |
| Peak RAM: reader + model server | — | 1.2 GB | 1.2 + 3.3 GB | 1.2 + 1.9 GB | reported |

**Selection (rule fixed before the run):** only `glm-ocr` passes every gate item, so it wins.
Docling reads the document, and GLM-OCR reads each table's structure, spelt in the PDF's own
words.

**Diagnosis, table by table:**

- **Docling alone:** the four SDS transport tables score 0.333–0.500. Their two-line header
  ("14.1 / UN / ID") and columns of dashes are misaligned by TableFormer. The GLM-OCR grid
  reads all four fully.
- **PaddleOCR-VL:** loses rows in three mixture tables (0.429–0.667) and one datasheet table
  (0.750).
- **Misses common to every arm, from the truth side:**
  - the AMAGEL exposure table's dashes are drawn lines with no text layer, so no parser can
    spell them (that table is 0.800 for all arms);
  - the Eco-render Natural Finish datasheet's "W1" is printed in a font where 1 and I look alike, and the text layer differs from
    the truth.
- **GLM-OCR's one real miss:** a UK-REACH number wrapped across two lines (c068, 0.833).

**Also decided by this experiment:**

- Neither model's transcription passed its bar in round 2. The 8 low-text pages therefore
  stay figures, found through alt text and image search (S3), and are not transcribed.
- Known risks carried into S2 ingestion:
  - docling-parse drops glyphs in the One Click LCA font; test docling-parse 7.22.1 first,
    measured before any upgrade;
  - the Docling crash on the IWI Installation Guide needs a retry, or another document
    converted first, in a fresh process;
  - GLM-OCR must run with the generator stopped: about 3 GB of VRAM and 3.3 GB of RAM, about
    1.1 h for Lime Green's PDFs.

## After X8: docling-parse 7.22.1 (design and gate)

Written on 28 September 2026, before the update was installed.

**Problem.** docling-parse 7.21.0 and 7.22.0 treat character code 32 as a word break, even
when the font's ToUnicode map puts a letter there ([#359](https://github.com/docling-project/docling-parse/issues/359)).
Subset TrueType fonts renumber their glyphs, so code 32 can be any letter. In round 2's
carbon-footprint report it was "u" in the regular weight ("Man fact rer") and "f" in the
bold ("GWP- ossil"). A scan of every Lime Green PDF's fonts finds **5 of 98 documents, 7
pages**: the three carbon-footprint reports and the Forte and Silicate Render datasheets.

On those pages, Docling's own text keeps only 0.469–0.909 of the text layer's words. The
recovery step adds 8–63 raw lines per page, so the index loses no words, but those lines
carry no table or section structure.

**Fix.** docling-parse 7.22.1 (MIT, 28 September 2026) "treat[s] a source byte that decodes
to a visible glyph as text, even when that byte is 32" ([PR #361](https://github.com/docling-project/docling-parse/pull/361)).
It also changes two other things:

- word boundaries for short headings and positioned text;
- curly double quotes now fold to `"` rather than `'` ([PR #349](https://github.com/docling-project/docling-parse/pull/349)).

So its effect elsewhere must be measured too.

**Gate** (baselines saved from 7.22.0 in `data/runs/`):

1. On each of the 7 pages, Docling's own text (recovered lines left out) keeps ≥ 0.99 of the
   text layer's words.
2. The `docling` arm, re-scored on `x8-pages`, `x8-pages-r2` and `x8-pages-r3`, is no worse
   on any registered measure, pooled or page by page. A drop on any page is diagnosed
   before adoption.
3. The selected configuration (`glm-ocr`) on `x8-pages-r3` still passes round 3's gate,
   with values placed no lower than 0.984.
4. `scripts/check.py` passes.

If the gate passes, 7.22.1 becomes the ingest group's floor (`docling-parse>=7.22.1`).
Otherwise the lockfile returns to 7.22.0.

**Result** (28 September 2026). Outputs are in `data/runs/docling-parse-7221/`.

| Item | 7.22.0 | 7.22.1 | Verdict |
|---|---|---|---|
| 1. Own-text words kept, 7 pages | 0.469–0.909 | 0.469–1.000 | **fails as written** (4 pages below 0.99) |
| 2. `docling` arm, three sets, page by page | — | 5 page measures better, 0 worse | pass |
| 3. `glm-ocr` on round 3 | 0.984 (lowest 0.800) | 0.984 (lowest 0.800) | pass |
| 4. `scripts/check.py` | — | 339 tests, all checks | pass |

On item 1, three pages recover fully:

- Hemp Binder carbon footprint: 0.884 → 0.993;
- Forte p2: 0.868 → 1.000;
- Silicate Render p2: 0.909 → 1.000.

Of the four below 0.99, none is caused by the update:

- **Forte p1 (0.986) and Silicate Render p1 (0.945):** every missing word is a split in
  the reference itself ("decora tive", "spra y", "o ther"). pypdf breaks kerned words and
  Docling now reads them whole.
- **Solo and Board Adhesive carbon footprints (0.469, 0.524, identical in both versions):**
  whole regions are missing from Docling's reading, the left column's "Product Carbon
  Footprint" and "Generated with One Click LCA…". This is a separate loss, which the recovery
  step catches (63 lines each) and which needs its own diagnosis.

**Finding about the comparison.** The first comparison used baselines run before round 3's
code change, and seemed to show round 1's sentences dropping (0.989 → 0.978). At equal
code, 7.22.0 gives the same 0.978. The drop comes from round 3's change: a table header now
lives only in the whole-table element, which the recovery step counts as text but the scorer
leaves out of the text measures (round 1 p16). Baselines for item 2 were therefore re-run
at the same commit with 7.22.0, restored offline from the uv cache.

Gate item 1 fails as written, so the decision on adoption goes to the user.

**Decision (user, 28 September 2026):** adopt 7.22.1, pinned as the ingest group's floor.
Gate item 1's shortfall is recorded above as unrelated to the update. The region loss on the
two carbon-footprint pages is diagnosed separately.

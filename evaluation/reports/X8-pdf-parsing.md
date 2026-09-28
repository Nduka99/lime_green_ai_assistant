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

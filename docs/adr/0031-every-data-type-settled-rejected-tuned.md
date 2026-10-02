# 0031. Every data type after X42–X47: what is settled, what was rejected, what is still being tuned

- Status: Accepted. This record is the reference to check before proposing any change to
  reading or retrieval.
- Date: 2026-10-02
- Origin: X42 (web reading), X43 (every data type), X44 (search channels, ADR 0030),
  X45–X46 (closing gaps), X47 (document relevance and the data-type ladder). Reports in
  `evaluation/reports/`.

## Context

- The assistant answers from one online resource: the site's pages, the files they link,
  the pictures they show, and two GOV.UK documents.
- Between 28 September and 2 October each data type was added and measured. Several
  fixes were tried and rejected on evidence; others are settled.
- Without one record of all this, the same ideas were proposed again: a separate Word
  reader after Word-via-PDF was settled, and a document re-read on an unchecked
  diagnosis. This record lists each decision with its evidence, so that does not
  happen again.

## Settled (do not re-propose; change only with new evidence)

**Sources**
- **Sources in scope.**
  - The site's 160 pages, its linked PDFs and Word declarations, and the pictures they
    show.
  - GOV.UK *IWI guidance* and *Approved Document L* (OGL), in their own channel.
- **Left out.**
  - The *25-Year Environment Plan*: general environment policy, out by the user's
    choice (X44 F5).
  - SPAB and ASBP: link only (no reuse terms).
  - YouTube: link only (captions need the owner).

**Web pages**
- **The reader.** `limespec.webpage` lays out lines as a browser does, with heading
  levels and section paths and site furniture removed by component. It was measured
  against judged ground truth: W1 recall 1.000 and precision 0.993; held-out W2b
  1.000 and 0.988 (X42). Docling's HTML backend and trafilatura were measured worse.
- **Passage form.** The page form: sections packed with path context (W3).
- **Links.** A citation opens the online source; a text fragment marks a quote on a
  page, and `#page=N` marks a page of a PDF (W4). A picture's citation opens its page
  or document page with no fragment (X44 G6).
- **Card descriptions (F3a).** A link card's description is read only where no other
  page holds it; the truths were corrected as `web-pages-v2` and
  `web-pages-holdout-v2` (X44).
- **Callouts (A2).** A callout is content on the page it is about.
- **Contact information (X45 E1).** The page's `contentinfo` landmark, the same footer on
  all 160 pages, is read once from the home page: phone, opening hours and address.
- **Swatch cards (X45 E2, X46 R1).** A colour swatch card keeps its own lines, and lines
  every card in the grid shares are stated once after the colours.

**PDFs**
- **The reader.** Docling for layout and reading order; GLM-OCR for table structure,
  spelt in the PDF's own words; pdfium draws pages and decides which words are visible;
  missing visible words are recovered where they stand. One process per file
  (D82–D89, ADR 0027).
- **Passages.** Page-sized, with tables inline (X9).
- **Quote matching.** Typography is folded, and spacing is forgiven only at digits
  (D89).
- **Number ranges (X45).** A range broken across lines after its hyphen gets its hyphen
  back ("12-36hrs", "EN 13501-1").

**Word files**
- LibreOffice renders each file to PDF, which then goes through the PDF reader, with
  `layout.side_by_side` joining a label to its value: pairs 0.825 → 0.965 (X43 A3a).
- **There is no separate `.docx` reader** (D114).

**Pictures**
- **Passages.** One passage per picture, from its own words: an alt text of 5 words or
  more, and GLM-OCR's reading. The OCR gate passed with recall 0.971 and precision
  0.998 (X43 B2).
- **OCR replies that are not text.** An unfinished OCR reply is no text (X43). So is a
  reply that is only markdown fences or rules (X44 F1).
- **Pictures are ranked** by their own words and by SigLIP2 (text tower in the API,
  vectors stored per picture).
- **Each search adds** its 2 best by words and its 2 best by SigLIP2 (UniDoc-Bench's
  split). This beat SigLIP2 alone on `image-facts`, 0.825 vs 0.650, and on the fresh
  `picture-probe`, 0.938 vs 0.688 (X44 amendment 1).
- **At most 4 pictures per answer**: the generator's request limit (X43 B4).
- **Picture claims** stay behind `LIMESPEC_PICTURES` until E's run decides them (X43 B5).

**Retrieval**
- **Search.** Postgres + pgvector + pg_textsearch BM25, fused, then bge-reranker; the
  Qwen3-Embedding-4B embedder runs on the CPU (D55, D104).
- **Channels** (ADR 0030).
  - Company content fills a search's 8 places.
  - Pictures and guidance are added after it.
  - Guidance enters only where the reranker puts it above the company's 8th passage.
- **Scoped search** for named products (ADR 0028); a search per part of a question.
- **Model calls.** Each answer remembers its model calls, so no pair is scored twice:
  scores are identical alone or batched, and the top 8 matched on 60 of 60 questions.
- **Speed.** SigLIP2's vector is computed during the query embedding: search p95 1.77 s
  → 1.31 s (X45 T1, T2).
- **Price fence** (D79).

**Measurement**
- **Evidence matching (X44 M1).** Evidence is matched as the generator reads a passage:
  title, section and text.
- **Rules before runs.** Rules are written before runs; every set is registered before
  use; a selection is confirmed on a fresh set it was not tuned on (`picture-probe`,
  `picture-probe-2`).
- **One change per build.** Changes are measured from the last known-good index (X47
  ladder). X43 combined four additions in one build, and later arms were judged against
  baselines that held other changes. That was the main source of confusion in X44–X46.

## Rejected (tried and measured; do not retry without new evidence)

| Idea | Why it failed | Where |
|---|---|---|
| Docling's or trafilatura's HTML reading | Worse recall and precision against judged truth | X42 W2 |
| A link card's blurb read by a linked-page test | Precision −0.027 / −0.043 on the truths | X43 A2 |
| Docling's own Word reader | Duplicated boxed text, made bold lines into headings | X43 A3a |
| A separate `.docx` reader | Breaks the one-pipeline decision (A3a) | D114 |
| Picture passages for every picture, words or not | Pictures with no words matched any question naming their page: web facts 0.969 → 0.932 | X44 diagnosis |
| GOV.UK guidance in the company search | Outranked Lime Green's own pages | X44 diagnosis |
| SigLIP2 pooled before the text reranker | The reranker reads only text: 0.500 vs 0.850 | X43 B3 |
| Word and SigLIP2 picture rankings fused into one | Moderate pictures displaced each retriever's best: 0.475 vs 0.650 | X44 |
| Generated picture descriptions (F6) | 63 vs 62 of 76 picture questions, within noise; 2 h 50 min of GPU. Descriptions stay on disk | X44 |
| Compiled-list descriptions *instead of* unique card text (F3b) | v2 −3 | X44 |
| Moving Docling's words by page geometry (E3, E3′) | 1,592 and 460 moves; 1 of 30 sampled true. Paragraph continuations in a neighbouring column look identical to misplaced values | X45, X46 |
| Re-reading with every Docling box | Docling records one box for these elements; its reading-order step merges continuations without their box | X46 (verified on 3 pages) |
| More than 2 pictures per retriever | Under the cap of 4, no larger k changes what a search gives | X45 amendment 1 |
| Pruning the 2014 technical sheets | Each is its product's only technical sheet | X47 |
| De-duplicating safety data sheets | Each is evidence for its own product; one copy would cite the wrong product | X44, X47 |

## Being tuned (open; decided by measurement)

- **E4, compiled-list descriptions as well as unique card text.**
  - Clean comparison (version 28 vs 29): +17 parts over the four replays, and v2 −1.
  - Kept by its rule.
  - It helps list questions (v3 +11) and crowds others, so it is the first candidate
    for routing by question type.
- **v2's shortfall.** Version 25 had 83; version 29 has 81 (bar 82). The ladder isolates
  the cause (step L1 adds the web-reading changes alone).
- **Question-type routing.**
  - Apply E4, more picture places, and guidance only to the question types they help;
    routing only ever adds to the company search.
  - It is researched and planned in the next chat, before E.
- **Known gaps.**
  - Two Word declarations' fire and strength classes (one template). To be fixed inside
    the reading.
  - Wordless drawings beyond each retriever's first 2 (`image-facts` 0.825; bar 0.850).
  - A look-alike safety data sheet (kb28).
- **The data-type ladder (X47).** Version 17 → web reader → Word → GOV.UK → pictures →
  E4, one change per step. Running when this record was written; its result decides
  which additions stay.
- **Document relevance (X47).**
  - News, case studies, inspirations and EPD/carbon reports are measured by leaving each
    out.
  - Removal is the user's decision.

## Consequences

- A new proposal names the settled line or rejected row it is consistent with.
- An idea in the rejected table needs new evidence before it is tried again.
- The index that serves E is chosen from the ladder and the router experiment. It is
  not live until it passes its gates.

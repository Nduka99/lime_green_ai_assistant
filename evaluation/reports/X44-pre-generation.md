# X44. Production-ready extraction and retrieval, before generation

Design, rules and gates written on 1 October 2026, before any of them runs. The plan was
approved the same day, after index version 21 failed X43's C gates.

## Question

Can every data type of the online resource (pages, PDFs, PDF tables and figures, pictures,
Word declarations, GOV.UK guidance) be read and found as precisely as the text pages
already are? This covers everything before generation. Generation is measured afterwards,
with held-out v6, in its own plan.

## What version 21 showed (measured 1 October)

Version 21: 2,600 passages (pages 441, Lime Green PDFs 1,024, GOV.UK 584, Word 12,
pictures 539).

| Gate (X43 C) | Bar | Version 21 | Result |
|---|---|---|---|
| Replay frozen90 | ≥ 102 parts | 105 | pass |
| Replay v2 | ≥ 82 | 82 | pass |
| Replay v3 | ≥ 75 | 68 | **fail** |
| Replay v4 | ≥ 118 | 107 | **fail** |
| `web-facts` vs version 19 | not lower | 0.932 vs 0.969 (−0.037 [−0.071, −0.012]) | **fail** |
| `x9-tables` vs version 17 | within 1 | 0.980 vs 0.978 (4 gained, 0 lost) | pass |
| `web-links` | 0 problems | crashed (empty picture text) | not scored |

Diagnosis, by mechanism:
1. **Picture passages crowd text search.** Every picture became a passage, words or not:
   - 196 passages are empty;
   - 75 hold only GLM-OCR's empty reply, a markdown code fence;
   - 101 hold one or two words;
   - each is embedded as its page title plus "Image › section", so it matches any
     question that names its page.

   `web-facts` lost 13 facts and gained none, and version 21 still holds all 13. Among the
   passages that displaced them, pictures appear 22 times.
2. **GOV.UK guidance crowds company pages.** Approved Document L, the IWI guidance and the
   25-Year Environment Plan (325 passages of general environment policy) took places 16
   times on those 13 facts. On the customer sets they take at most 2% of the passages given.
3. **What the new web reader drops.** Every sentence of 6+ words in version 17's pages was
   looked for in version 21. Version 21 lacks 18 sentences in the whole site:
   - 10 card descriptions no other page holds: the home page's categories, the Silic8
     card ("we don't rely on acrylics or resins") and the Warmshell system cards;
   - 5 content sentences: Cotswold Revival case study ×2, a home-page testimonial, a
     stockist's name, a job duty;
   - 3 furniture lines.

   X42's truth judged every card description furniture, so X43's A2 rule could not pass
   its gate. The truth was wrong for descriptions that no other page holds.
4. **Most of the v3/v4 loss is the scorer.** The lost parts quote product cards as
   "Name + description":
   - version 21 holds the names, under the page's own heading ("Products available in
     Ochre colour") and in the compiled list;
   - it holds each description once, on the product's own page, under that product's
     heading;
   - the generator reads each passage with its page title and section (`answer.py`), but
     reach matched quotes against the passage text alone.
5. **Pictures:**
   - Arm results on `image-facts`: text only 0.325; SigLIP2 pooled before the text reranker
     0.500; SigLIP2's best 2 in places 7–8 (the quota) 0.850 (+0.525 [+0.375, +0.675]).
   - The pooled arm fails because the reranker reads only text.
   - SigLIP2's sigmoid score cannot gate pictures: the median best match is 0.979 on text
     questions and 0.976 on picture questions, so a product question matches its product
     photo just as strongly.
   - The quota's 6 misses: 3 technical drawings and 2 photos with no words, and a swatch
     named only by a one-word alt text.
6. Search time is unchanged (median 0.75 s per search on versions 17 and 21). 109 of 1,031
   document passages repeat another document's text (look-alike safety data sheets). Each
   copy is evidence about its own product, so they are left to scoped search.

## Research

- **Separate retrievers per modality.** Separate text and image retrievers, each giving its
  own top-k, beat joint multimodal embeddings on precision (UniDoc-Bench, arXiv
  2510.03663: text + image recall 0.867 and precision 0.479, joint embeddings 0.870 and
  0.341). Its fusion takes the top 5 of each, appended, with no reranker.
- **Qwen3-VL-Embedding is not ready here.** It needs a patched llama.cpp fork (llama.cpp
  discussion #19516).
- **Captions for pictures.** A vision model's caption of each picture and chart, indexed
  for search, is the production practice for questions about images (NVIDIA RAG Blueprint,
  "image captioning"; it is off by default only for ingestion cost).
- **Repeated web text.** Repeated segments are removed across a site and the canonical
  copy kept (RefinedWeb, arXiv 2306.01116; FineWeb; Trafilatura `deduplicate`).
- **Authority tiers.** Official sources rank above general guidance, through a separate
  index or a prior (J. Liu, "Authority in RAG systems", 2025; Unstructured, metadata in
  RAG).
- **GLM-OCR's fence.** Its empty markdown fence is its output when it finds no text
  (Ollama issue #14474, llama.cpp discussion #19721).
- **Nugget keys.** Evidence keyed as short facts (nuggets), not passage-bound spans,
  survives changes in segmentation (TREC 2024 RAG, AutoNuggetizer, arXiv 2411.09607).

## Measurement first

- **M1. Evidence is matched as the generator reads it.** Each passage's page title, section
  and text, in that order, are searched for the evidence. This applies to reach (replay),
  `web-facts`, the quote and table lookups and `kb-probe`.
- **M2. Tool faults.** `web-links` handles a passage with no text line. `web-compare` reads
  a set's own summary when a file holds several.
- **Baselines.** Versions 17, 19 and 21 are scored again under M1 before any fix is
  scored. Every gate compares with these rescored numbers.

## `kb-probe`: the multimodal retrieval set

- **Writing.** About 64 questions, written from sources as a visitor sees them:
  - pages: Chromium's visible text and screenshots;
  - PDFs: pypdf text and drawn page images;
  - Word: LibreOffice's layout;
  - pictures: the image files themselves.

  Never from this pipeline's passages. Sources are drawn with seed 71 from
  `data/catalogue-v6.json`.
- **Strata:**

  | Stratum | Questions |
  |---|---|
  | Web content pages | 8 |
  | Listing and card pages | 6 |
  | PDF text | 8 |
  | PDF tables | 6 |
  | PDF figures and charts | 6 |
  | Pictures, as they look | 8 |
  | Pictures holding text | 6 |
  | Word declarations | 6 |
  | GOV.UK guidance (IWI, Approved Document L) | 6 |
  | Cross-type | 4 |
- **Evidence as nuggets.** Each is one of:
  - a span of at most 15 words that states the fact, with every page or document that
    holds it;
  - a picture, by id; a stored copy counts (`imagesets.copies`).
- **Success.** Every nugget of the question is held by what one search gives: the company
  top 8 plus the appended pictures and guidance. A text nugget counts only in a passage
  from one of its holders.
- **Sealing.** The set is registered before any fix is scored on it, and it is never used
  to design a fix. It is the unseen check for fixes designed on `web-facts`, `image-facts`
  and the replays.

## Fixes

- **F1. OCR replies.** A reply that is only code fences or markup holds no text.
- **F2. Search channels.** Each passage carries a channel, set at build: `company` (pages,
  Lime Green PDFs, Word), `picture` or `guidance` (GOV.UK).
  - **Company:** keyword and vector rankings, fused, then the reranker; top 8, as today.
  - **Pictures:** best 2 **appended** per search, at most 4 per question.
    - Arm **S:** SigLIP2's ranking alone.
    - Arm **W+S:** the keyword and vector rankings over pictures that have words of their
      own, fused with SigLIP2's ranking.
    - SigLIP2's text tower runs in the API process on the CPU (`src/limespec/siglip.py`).
  - **Guidance:** the reranker scores the channel's best candidates. Up to 2 are appended,
    and only those scoring above the company channel's 8th passage. Guidance enters on
    merit, never displaces company content, and is labelled general guidance.
- **F3. Card text.**
  - **F3a:** a card's description is content when no other page of the corpus holds its
    text (normalised as `webpage` normalises lines).
  - **F3b:** the compiled list passage of a listing page holds each card's name and
    description.
- **F4. Reader losses.** The rule that drops the 5 content sentences is found and fixed
  generally.
  - The truth is corrected as a new set, `web-pages-v2`: `web-pages` with each card
    description no other page holds marked as content.
  - Gate: on W1 (`web-pages-v2`) and W2b, recall and precision stay within 0.005 of
    today's values, and every corrected line is read.
- **F5. Scope.** The 25-Year Environment Plan leaves the index (the user, 1 October). A
  sealed v6 case citing it is reported as unanswerable.
- **F6. Picture descriptions** (the user approved the GPU time).
  - The generator that passes B4 describes each picture in two or three sentences: what
    it shows, the materials and colours, and what a drawing or chart depicts. It names no
    brand or number that is not visible.
  - Each description is search context for its picture passage. It is never quoted and
    never shown.

## Builds and arms

- **Two builds** (stored vectors reused):
  - build X: F1, F2, F3a, F4, F5 and F6;
  - build Y: the same with F3b in place of F3a and without F6.
- **Why two builds suffice.** The channels are disjoint:
  - F3 changes only company passages, so X and Y differ in the company channel by F3
    alone;
  - F6 changes only picture passages, so they differ in the picture channel by F6 alone.
- **Picture arms** S and W+S are chosen at query time on either build.
- **Selection rules:**
  - **F3:** F3b is taken over F3a only if, summed over the four replays, it reaches more
    parts and no set falls by more than 1. Otherwise F3a.
  - **Pictures:**
    - choice: the arm (S, W+S, W+S with F6) with the highest Success@given on
      `image-facts`, among arms whose interval against S (pictures resampled) lies above
      0; otherwise S;
    - confirmation: the chosen arm must not fall below S on `kb-probe`'s picture strata.

## Gates for version 22 (it serves nothing until all pass)

- **G1.** Replay (M1): every set not below version 17 (M1) by more than 1 part.
- **G2.** `web-facts`: not below version 19, interval not below 0.
- **G3.** `x9-tables`: within 1 lookup of version 17.
- **G4.** `image-facts`: not below the quota's 0.850.
- **G5.** `kb-probe`:
  - text strata pooled ≥ 0.90; picture strata pooled ≥ 0.75; guidance ≥ 0.80;
  - no stratum below version 17 where version 17 holds its sources.
- **G6.** `web-links` reports zero problems, and `scripts/check.py` passes at 100%.
- **G7. Cost.**
  - Search p95 ≤ 1.5 s.
  - The API's RAM with SigLIP2's text tower is measured.
  - At least 6 GB of RAM stays free with every server up.

## Results

*(added step by step)*

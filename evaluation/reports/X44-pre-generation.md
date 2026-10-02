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

**Amendment 1 (1 October, after version 22's picture results, before the new arm
runs).**
- **The fusion arm was a design error.** W+S fused the word and SigLIP2 rankings into
  one ranking (RRF). UniDoc-Bench, the evidence it cited, takes each retriever's own top
  k and appends them; it does not fuse them. Fused, a picture ranked moderately by both
  retrievers displaces each one's best: on version 22, `image-facts` falls from 0.650
  (S) to 0.475 (W+S).
- **New arm W∪S:** each search adds its 2 best pictures by their own words, then its 2
  best by SigLIP2 that are not already added; at most 4 pictures per question, as
  before.
- **A fresh set decides it**, because `image-facts` and `kb-probe`'s pictures have both
  now been seen:
  - `picture-probe`: 16 pictures drawn with seed 72 by `imagesets.picture_draw`;
  - none of them in `image-facts`, `image-text` or `kb-probe`;
  - questions written from the pictures by `image-facts`' rules;
  - sealed before W∪S runs.
- **Rule:** W∪S replaces S if, on `image-facts` and `kb-probe`'s picture strata pooled,
  its interval against S lies above 0, and on `picture-probe` it is not below S.
  Otherwise S stays.
- **G4's bar** (0.850) is unchanged.
- **The 78 pictures F4 adds** (the four Inspirations galleries, slideshows of pictures)
  get SigLIP2 vectors before builds X and X0. Build X0 is X without F6, so F6 is judged
  between two builds holding the same 617 pictures.

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

**M1 baselines (1 October; `data/runs/x44/m1/`).** Evidence matched as the model reads
it:

| Measure | Version 17 | Version 19 | Version 21 |
|---|---|---|---|
| Replay frozen90 (parts of 125) | 103 | — | 105 |
| Replay v2 (of 140) | 83 | — | 82 |
| Replay v3 (of 105) | 76 | — | **80** (68 before M1) |
| Replay v4 (of 130) | 119 | — | 114 (107 before M1) |
| `x9-tables` Success@8 | 0.978 | — | 0.980 |
| `web-facts` Success@8 | 0.921 | 0.969 | 0.932 |
| `web-links` problems | — | — | 90 |

- M1 removed most of the v3 and v4 drop: the evidence sat under a product's heading.
- Version 17's numbers are unchanged under M1.
- What remains on v4 is the 2 truly lost card descriptions plus crowding, the causes F2
  and F3 address.

**`kb-probe` sealed** (`1843bb6`, registered before any fix is scored):
- 64 questions, seed 71: 8, 6, 8, 6, 6, 8, 6, 6, 6 and 4 per stratum, as designed.
- Draws restricted to the indexed scope (F5): two figures first drawn from the 25-Year
  Environment Plan were redrawn before any question was written.
- The draw drew the guidance stratum's 6 questions with replacement: 1 Approved
  Document L, 5 IWI guidance.
- Nuggets: 51 text spans in 44 questions, and 20 pictures. Spans that many documents
  share
  ("Shelf life: 12 months", product names on a colour page) count only in their own
  source (`own`).
- kb05 (opening hours) is held by all 160 pages: it tests whether the footer is read.

**F3a and F4, against the corrected truth** (`662afe9`):
- `web-pages-v2` adds the 6 card descriptions no other page holds, all on `products`;
  `web-pages-holdout-v2` adds none. Both were registered before the reader was scored
  on them.

| Truth | Recall | Precision | Headings | Section paths | Lists |
|---|---|---|---|---|---|
| W1 v2 (today on v1) | 1.000 (1.000) | 0.9927 (0.9926) | 0.986 | 0.967 | 1.000 |
| W2b v2 (today on v1) | 1.000 (1.000) | 0.9875 (0.9875) | 1.000 | 0.850 | 1.000 |

- The gate passes: the restored descriptions are read (recall 1.000 on v2), and every
  measure is within 0.005 of today's.
- F4's diagnosis narrowed the loss:
  - of the 5 "content sentences" the sentence diff found, 3 are read (the diff joined a
    bold lead to its paragraph);
  - the home page's testimonial was dropped as a "related cards" slideshow, so a
    slideshow is now furniture only when it is a slideshow of link cards;
  - "Derek March Brick and Lime Supplies" is a link card in the news feed, and stays
    furniture.

**G6 (`a3e1953`).** All 90 `web-links` problems were picture passages: alt text and
text read in a picture are not the page's text, so a text fragment built from them
finds nothing. A picture's citation now opens its page, or its document at the page.

**B4, the serving check** (`data/runs/x43/b4-*.json`; 8080 and 8081 stopped):

| Generator | GPU | Text replies with the projector loaded | 20 requests with 4 pictures each |
|---|---|---|---|
| Qwen3.6 | 4.6 GB | identical, 10 of 10 (9.6 s vs 9.7 s) | all completed, 36.8 s each (pictures encoded on the CPU) |
| Gemma 4 26B | 6.3 GB | identical, 10 of 10 (14.8 s vs 14.1 s) | all completed, 35.9 s each |

Both pass B4: every request completed, peak GPU within 7.4 GB, and text answers are
byte-identical with the projector loaded. Gemma 4 26B, the chosen generator (D107),
describes the pictures for F6. The 6 swatch readings failed in this window: they ran
while `layout.py` was being edited, which my edit had briefly broken on import. They
move to the F6 window.

**`kb-probe` on today's versions, plain top 8** (`data/runs/x44/kb-probe-v17.json`,
`-v21.json`). These are the company channel only, as served, so there are no pictures
or guidance:

| Stratum | Version 17 | Version 21 (ceiling) |
|---|---|---|
| Web content | 0.88 | 0.75 (0.75) |
| Listing and card pages | 1.00 | 1.00 |
| PDF text | 0.88 | 0.75 (0.88) |
| PDF tables | 0.83 | 0.83 (1.00) |
| Word | 0.00 | 0.67 (0.67) |
| Cross-type | 0.25 | 0.50 (1.00) |
| Guidance, pictures | 0 | 0 (all in the version) |

Its extraction misses are evidence the version lacks:
- kb05, opening hours: the site footer is furniture on every page, so the facts in it
  are nowhere;
- kb06, free colour samples;
- kb17, a drying time;
- kb49 and kb54, a Word declaration's fire and strength classes.

These were found on `kb-probe`. So they no longer count as unseen checks for their
fixes, and each fix is checked on other sets:
- **Number ranges (`9e7188e`).** Docling joined a range broken across lines after its
  hyphen: "12-36hrs" became "1236hrs", "EN 13501-1" became "135011", and "18-25mm"
  became "1825mm". The text layer keeps the PDF's own characters ("12-\r\n36hrs"), and
  a hyphen after a digit never splits a word. So at passage building each such range
  gets its hyphen back: whole tokens only, and never where the page also shows the
  halves joined. Across the 109 documents it mends exactly those 3 numbers, each
  checked by hand.
- **Word declaration pairs (not fixed in X44).** Docling's layout step put the
  right-hand value "Class B1" inside the paragraph of the next row's label ("Strength
  Class Class B1"), so `side_by_side` never sees a separate value. Two of the 8
  declarations, sharing one template, lose their fire class that way. This is the
  residual behind `docx-pages`' pairs 0.965. The general fix is to read each line of
  the Word file's own text and check the rendered reading against it; it is left for
  the next round, with this risk recorded.
- **The site footer and the sample cards** are left for the next round as well. Builds
  X and Y may differ only by F3 and F6, so a company-channel change now would confound
  them.
  - The footer could be read once, as the site's own page.
  - The sample page's colours are a colour grid, read as names (X42's rule). Each
    card's "Order this colour sample / Free" is a card button and tag under that rule.

**F3: the card arm, by its rule.** Text gates with `--channels`; pictures do not
change these:

| Measure (bar) | Version 17 | Version 22: F3b, compiled lists | Version 23: F3a, unique descriptions |
|---|---|---|---|
| Replay frozen90 (≥ 102) | 103 | 112 | 108 |
| Replay v2 (≥ 82) | 83 | **80** | 83 |
| Replay v3 (≥ 75) | 76 | **89** | 78 |
| Replay v4 (≥ 118) | 119 | 119 | 118 |
| `web-facts` vs version 19 (0.969) | 0.921 | 0.952 (−0.017 [−0.052, +0.000]) | 0.966 (−0.003 [−0.009, +0.000]) |
| `x9-tables` (17: 0.978) | 0.978 | 0.980 | 0.980 |

- F3b reaches more parts over the four replays (400 against 387), but falls on v2 by 3
  against F3a, and the rule allows 1. **F3a is selected**, and its build passes G1–G3.
- The channels removed `web-facts`' crowding: version 21 scored 0.932, version 23
  scores 0.966, one fact from version 19.
- F3b gains 11 parts on v3, whose list questions ask for what each product is. Keeping
  the unique descriptions in the page and the compiled list's descriptions as well
  was not registered as an arm; it is the next round's candidate.

**Pictures and F6: builds 24 (F3a + F6) and 25 (F3a), 571 pictures each, every one
with a SigLIP2 vector** (`data/runs/x44/v24/`, `v25/`):

| Set | 24: S | 24: W+S | 24: W∪S | 25: S | 25: W+S | 25: W∪S |
|---|---|---|---|---|---|---|
| `image-facts` (40) | 0.650 | 0.675 | 0.825 | 0.650 | 0.475 | 0.825 |
| `picture-probe` (16, fresh) | 0.688 | 0.688 | 0.875 | 0.688 | 0.625 | **0.938** |
| `kb-probe` pictures (20) | 0.600 | 0.900 | 0.800 | 0.600 | 0.600 | 0.700 |

- **Amendment 1's rule adopts W∪S.**
  - On version 25 it beats S on `image-facts`: +0.175 [+0.075, +0.300].
  - On the fresh `picture-probe` it is not below S: +0.250 [+0.062, +0.500].
  - The same holds on version 24.
- **F6 is not adopted.**
  - With W∪S, the two builds tie on `image-facts` (33 of 40).
  - F6 is one question lower on `picture-probe` and two higher on `kb-probe`'s
    pictures: 63 against 62 of 76 pooled, within noise. Rule 5 keeps a change only if
    it wins beyond noise.
  - The descriptions help the fused arm most (W+S 0.475 → 0.675 on `image-facts`).
  - All 617 descriptions stay on disk (`data/images/<id>.json`); generating them took
    2 h 50 min of GPU (16.5 s per picture).
- **The decisions are applied in `0eea06d`:** W∪S is the only picture ranking, and the
  F6 and F3b code is removed (git keeps it).

**Version 25 against the gates:**

| Gate | Bar | Version 25 + W∪S | Result |
|---|---|---|---|
| G1 | each replay not below 17 by more than 1 | 108 / 83 / 78 / 118 | pass |
| G2 | `web-facts` not below 19 | 0.966 (−0.003 [−0.009, +0.000]) | pass |
| G3 | `x9-tables` within 1 | 0.980 | pass |
| G4 | `image-facts` ≥ 0.850 | 0.825 | **fail** (33 of 40; 34 needed) |
| G5 | `kb-probe` text ≥ 0.90, pictures ≥ 0.75, guidance ≥ 0.80, no stratum below 17 | text 0.841, pictures 0.700, guidance 1.00; web content 0.75 vs 0.88 | **fail** |
| G6 | `web-links` 0 problems | 0 of 4,158 links | pass |
| G7 | p95 ≤ 1.5 s; API RAM measured; ≥ 6 GB free | p95 1.77 s (median 1.51 s, twice); 3.4 GB; 8.2 GB free | **fail** on time |

**Readout.**
- Version 25 is the best index so far: every data type is found in its own channel,
  the text sets hold or rise, and the guidance stratum went from 0 to 6 of 6.
- It does not pass G4, G5 and G7, so it serves nothing (ADR 0030).
- Every failure has a measured cause:
  - **G5 text (7 misses of 44):**
    - the site footer (kb05);
    - the colour-sample cards' "Free" (kb06), which version 17 read, so web content is
      one question below 17;
    - two Word declarations (kb49, kb54);
    - a look-alike safety data sheet (kb28; the answer path's scoped search names the
      product);
    - two cross-type questions asked as one search (kb61, kb63; the answer path searches
      each part).
  - **G5 pictures and G4:** drawings and photos that neither the pictures' own words
    nor SigLIP2 rank in their first 2.
  - **G7:** the three channels run one after another (an embedding, two searches, a
    joint rerank and SigLIP2's text tower per query).
- **X45** addresses these, in order:
  1. extraction (footer facts read once as the site's page; colour-grid sample tags;
     a line-level check of Word readings against the file's own lines);
  2. compiled-list descriptions kept beside the unique ones (+11 parts on v3);
  3. channels searched concurrently;
  4. picture places.

  Then E (generation) runs with v6 as the main set.

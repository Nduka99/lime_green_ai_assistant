# X45. Closing version 25's gaps: extraction misses, picture places, search time

Rules and gates written on 2 October 2026, before any run. The plan was approved the same
day, after X44 (ADR 0030) left version 25 short of three gates.

## Question

Version 25 passes the replays, `web-facts`, `x9-tables` and `web-links`, but fails three
gates:

| Gate | Bar | Version 25 |
|---|---|---|
| G4 `image-facts` | ≥ 0.850 | 0.825 |
| G5 `kb-probe` | text ≥ 0.90; pictures ≥ 0.75; no stratum below version 17 | text 0.841; pictures 0.700; web content 0.75 vs 0.88 |
| G7 search time | p95 ≤ 1.5 s | 1.77 s |

Can general changes close these gaps without losing anything the other gates hold? X45
needs no download, no GPU, and no server stopped.

## Diagnosis (read-only, 2 October, version 25)

1. **The site footer is never indexed.**
   - Its text is identical on all 160 pages: the phone number, "Opening hours Mon - Fri
     9:00am - 5:00pm", the address, and an "About Us" statement.
   - The reader drops it as furniture on every page, so these facts exist nowhere in
     the index (kb05).
2. **Colour-sample cards lose their own text.** The `.clr-grid` rule keeps each swatch's
   name only, so "Order this colour sample" and "Free" in each card's `.txt` are dropped
   (kb06). Version 17 read them.
3. **Words attached to the wrong element.**
   - In two Word declarations that share one template, "Class B1" sits on the "Reaction
     to fire:" line (x≈323), but Docling puts it in the next row's paragraph,
     "Strength Class Class B1" (box x 72–142; kb49, kb54).
   - Across the 109 readings, 224 of 18,731 text elements (in 53 documents) hold a word
     the page shows only outside the element's box. Many are box imprecision on the
     same line.
4. **Pictures beyond each retriever's first 2.** On `image-facts` and `kb-probe`'s
   pictures (60 questions), the target is first found:

   | Rank | Questions |
   |---|---|
   | 1–2 | 47 |
   | 3 | 3 |
   | 4 | 4 |
   | 5–10 | 3 |
   | below 10 | 3 |

   The 3 below rank 10 are drawings and photos with no words.
5. **Search stages run one after another.** Medians on 20 frozen90 questions:

   | Stage | Median |
   |---|---|
   | Query embedding | 412 ms |
   | Company SQL | 359 ms |
   | Company rerank | 328 ms |
   | SigLIP2 text vector | 173 ms |
   | Picture SQL | 119 ms |
   | Guidance SQL | 96 ms |
   | Guidance rerank | 270 ms (it sends the company's top 8 again) |

## Changes and their rules

- **E1. Repeated components read once.**
  - A component whose text is the same on every page of the build is read once, as a
    passage of the home page titled with the site's name.
  - It is found by measuring the pages, not named by class (RefinedWeb and Trafilatura
    keep one copy of repeated text).
- **E2. A colour-grid swatch keeps its own text.**
  - Its `.txt` lines are read after its name, without forms and buttons.
  - The price fence applies as everywhere.
- **E3. Misplaced words.**
  - At passage building, a word an element holds is moved out of it when:
    - the page shows it only on a pdfium line whose vertical span misses the
      element's box;
    - and the element's box shows no copy of it.
  - The moved word becomes a line at its own box, placed by `recovery.anchor`.
  - **Diagnosis first:** every move across the 109 readings is listed, and 30 drawn
    with seed 74 are read against page images. E3 proceeds only if at least 27 of the
    30 are true misplacements.
- **E4. Compiled descriptions as well as unique ones.** Each product grid's compiled
  list carries each card's description, beside F3a (X44).
- **T1. One rerank call.**
  - The company candidates and up to 8 guidance candidates are scored together; the
    company's top 8 are its best 8.
  - Guidance is kept where it scores above the company's 8th, at most 2 per search.
  - Check: the company top 8 identical to separate calls on 60 questions.
- **T2. SigLIP2's text vector computed during the query embedding request.**
- **P. Picture places.**
  - Each retriever's top k, interleaved by rank and capped at 4 per question. Arms:
    k = 2, 3, 4.
  - **Rule:** the highest Success on `image-facts` with `kb-probe`'s pictures (60
    questions; ties go to the smaller k). On the fresh `picture-probe-2`, the chosen k
    must not fall below k = 2; otherwise k = 2.

## Sets

**`picture-probe-2`.**
- 16 pictures drawn with seed 73 (`imagesets.picture_draw`), excluding every picture in
  `image-facts`, `image-text`, `kb-probe` and `picture-probe`, and the left-out
  environment plan.
- Pictures that qualify as in X43 amendment 1 (something a customer could ask to see;
  logos, signatures, plain pack shots and placeholders skipped).
- Questions are written from the pictures, and the set is registered before any arm
  runs.

## Builds and gates

- **Builds:** version 26 = E1–E4; version 27 = E1–E3. Both use T1, T2 and the chosen k at
  search time.
- **E4** is kept only if the four replays' summed parts rise and no set falls by more
  than 1 against version 27.
- **E1, E2:** W1 and W2b (`web-pages-v2`, `web-pages-holdout-v2`) within 0.005 of today on
  every measure; G6 zero link problems.
- **E3:**
  - `docx-pages` pairs above 0.965, the other measures held;
  - X8 rounds 1–3 rescored with no page measure falling;
  - `x9-tables` within 1 lookup of version 17.
- **G1–G7** as registered in X44, against the same baselines, on the chosen build.
- **If all pass:** ADR 0031 freezes the index for E.
- **If any fails:** the cause is reported and the decision goes to the user.

## Results

*(added step by step)*

**`picture-probe-2` sealed** (`1b8cf93`): 16 pictures (14 site photos and swatches, 2
figures), 7 with stored copies accepted.

**E3: fails its diagnosis rule; not built.**
- The rule as written would move 1,592 words across 50 documents. Of the 30 drawn
  with seed 74 and read against their pages (`scratchpad e3-sheet-*.png`), most are
  not misplaced words.
- **What the 30 are:**
  - paragraphs that continue in the next column or below a figure, whose stored box
    covers only their first part;
  - table rows Docling merged across cells;
  - running headers ("According to REACH Regulation…") merged into the element below.
- **The cause is the reading, not the rule.** An element keeps one box although
  Docling records one per part (`prov`). A correct test needs every part's box, so
  every document read again (~33 min, plus GLM-OCR's tables).
- That belongs to the next reading round, with the Word declarations' lost fire class
  (kb49, kb54) kept as a known risk until then.

**Amendment 1, before any picture-places run: P withdrawn.**
- An answer attaches at most 4 pictures (`MAX_PICTURES`, X43 B4's request limit), and
  `answer.with_extras` caps each question's pictures at 4. Each retriever's top 2
  already fill those 4 places.
- So any k above 2, interleaved or not, gives the same pictures for a one-search
  question. The diagnosis's ranks 3–4 are beyond the cap.
- `assistant.searched`, which the sets score, did not apply the cap. It now applies it,
  so the sets measure what an answer can attach.
- Raising the cap is a generation-cost question (B4: about 36 s per request with 4
  pictures) and goes to E.
- `picture-probe-2` is still scored on the final build as a fresh check of the union
  arm.

**T1, as built: a pair is never scored twice.**
- Each answer keeps its reranker scores by (question, passage text), as it keeps query
  embeddings. Guidance placement therefore scores only the guidance candidates, not
  the company's top 8 again.
- This is the plan's single call by other means: no restructuring of `answer.gather`,
  and the same check (identical company top 8).
- **Check passed on 60 questions** (30 `kb-probe`, 30 frozen90, version 25):
  - the company top 8 are identical, 60 of 60;
  - a passage's score is the same whether scored alone or with others (largest
    difference 0.000000): bge-reranker scores each pair on its own.

**E1, E2 and E4 built** (`819e199`).
- **E1:** the site's `contentinfo` landmark (WAI-ARIA's role for a page's contact and
  site information), read once from the home page.
  - It becomes one passage, "Contact us": phone, opening hours, address and the "About
    Us" statement.
  - This is the standard landmark, not a site class name.
- **E2:** each swatch card keeps its own lines.
  - The sample page now reads "Ochre / Order this colour sample / Free".
  - Colour pages are unchanged.
  - **Gate passed:** W1 (`web-pages-v2`) and W2b (`web-pages-holdout-v2`) are identical
    to before on every measure (recall 1.000 / 1.000, precision 0.9927 / 0.9875,
    headings, section paths, lists, alts).
- **E4:** `ingest --compiled-descriptions`.
- **Builds:** version 26 = E1 + E2 + E4 and version 27 = E1 + E2, built by scratch
  `x45-chain.sh` and gated by `x45-gates.sh`.

**Builds and gates** (`data/runs/x45/v26/`, `v27/`; versions built 2 October, 04:27 and 04:29):

| Gate (bar) | Version 25 (X44) | 27: E1 + E2 | 26: E1 + E2 + E4 |
|---|---|---|---|
| G1 frozen90 (≥ 102) | 108 | 107 | **111** |
| G1 v2 (≥ 82) | 83 | **77** | **80** |
| G1 v3 (≥ 75) | 78 | 78 | **89** |
| G1 v4 (≥ 118) | 118 | 118 | **121** |
| G2 `web-facts` vs 19 (0.969) | 0.966 | 0.966 [−0.009, +0.000] | 0.952 [−0.052, +0.000] |
| G3 `x9-tables` | 0.980 | 0.980 | 0.980 |
| G4 `image-facts` (≥ 0.850) | 0.825 | 0.825 | 0.825 |
| `picture-probe` / `picture-probe-2` (fresh) | 0.938 / — | 0.938 / 0.875 | 0.938 / 0.875 |
| G5 text (≥ 0.90) | 0.841 | 0.886 | 0.886 |
| G5 pictures (≥ 0.75) | 0.700 | 0.700 | 0.700 |
| G5 guidance (≥ 0.80) | 1.00 | 1.00 | 1.00 |
| G5 strata below 17 | web content | none | none |
| G6 `web-links` | 0 | 0 | 0 |
| G7 search p95 (≤ 1.5 s) | 1.77 s | — | **1.31 s** (twice; median 1.07–1.10 s; API 3.4 GB; 7.7 GB free) |

- **E4 is kept by its rule.** Version 26 reaches more parts than 27 on every replay (401
  against 380). It costs `web-facts` 5 facts (0.952 against 0.966).
- **E1 and E2 work.** `kb-probe`'s web content went from 6 of 8 to 8 of 8: the opening
  hours (kb05) and free colour samples (kb06).
- **T1 and T2 close G7:** p95 1.77 s → 1.31 s, with identical company results.
- **E2 costs v2 three parts** (version 25 83 → version 27 77, with one more lost to a
  ranking shift).
  - It reads every swatch card's "Order this colour sample / Free", 24 times over.
  - The sample page's colour list becomes a long, repetitive passage that outranks the
    page's "Order Samples" section and the sample terms, which hold v2's evidence
    (v2q009, v2q037: 5 of the 6 parts lost).
  - The general fix is to state lines that every card of a grid repeats once per grid
    (E1's principle within a page). It was not registered, so it is not applied here.

**Result: version 26 is the best index yet, but fails three gates as registered.**

| Gate | Version 26 | Bar | Cause |
|---|---|---|---|
| G1 v2 | 80 | 82 | E2's repeated card lines (above) |
| G4 | 0.825 | 0.850 | Drawings and photos with no words, below each retriever's first 2 and beyond the cap of 4 |
| G5 text | 0.886 (39 of 44) | 0.90 | See below |
| G5 pictures | 0.700 | 0.75 | Same cause as G4 |

G5's five text misses:
- kb49 and kb54: the Word fire and strength classes. The fix is E3 done properly,
  which needs every document read again keeping all of each element's boxes.
- kb28: a look-alike safety data sheet; the answer path's scoped search names the
  product.
- kb61 and kb63: two-part questions asked as one search; the answer path searches each
  part.

G2 holds within its interval; G3, G6 and G7 pass. As registered, the decision goes to
the user.

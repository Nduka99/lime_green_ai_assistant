# X43. Every data type: the multimodal knowledge base, and evaluations that cover it

Design, rules and gates written on 1 October 2026, before any of them runs. The plan was
approved the same day, after X42 fixed the web side.

## Question

The assistant's sources are one online resource: the site's pages, the files they link,
and the images they show. X42 measured and fixed how pages are read. What else does the
resource hold? Which of it can legally be used, and how does each kind enter the index
and the answers? And can the evaluation sets show how well each kind is used?

## The resource, by data type (measured 1 October)

| Data type | Count | Before X43 | Legal footing | X43 |
|---|---|---|---|---|
| Web pages | 160 (product 39, colour 29, case study 25, news 23, knowledge 22, other 22) | X42's reader, not yet indexed | the company's public site | indexed in the W3 form |
| Site PDFs | 98 documents, 584 pages (safety 33, technical 32, performance 16, guide 9, certificate 4, policy 4) | read and indexed (X8, X9) | the company's downloads | unchanged |
| PDF tables | 274 | indexed whole (X9) | — | unchanged |
| PDF figures | 875 in 96 documents (6 with caption text; 243 under 50 × 50 pt) | caption text only | — | cropped, become image passages |
| Declarations (.docx) | 8, linked from 7 product pages | not collected (`file_links` follows `.pdf` only) | the company's downloads | collected, read, indexed |
| OGL guidance | 3 gov.uk PDFs, about 314 pages | collected, never read | OGL-3.0, attributed | read, indexed as general guidance |
| Site images | 380 collected; 169 lazy-loaded (`data-src`) not collected, including the 30 colour swatches | not indexed; 52 have a descriptive alt text | the company's site | the rest collected; image passages |
| Videos | 5 YouTube videos | titles and links on pages | YouTube's terms; captions download only with the owner's authorisation | link and title only |
| NBS widget | 15 iframes | — | an "add to spec" button; the product records are NBS's | none |
| Cited sites | SPAB, ASBP | — | permission needed / no reuse terms (D72) | link only |

## A. Missing text, and X42's finish

1. **W3** is scored on its three builds and version 17 by X42's pre-registered rule.
2. **Two reader gaps** came from the existing keys (31 quotes the old extractor holds and
   the new reader does not). Both are fixed by a general rule, and the reader is scored
   again on W1 and W2b. The fix is kept only if W1 and W2b recall and precision stay
   within 0.005 of their frozen values.
   - **A link card's blurb** is kept when the page it links to does not hold that text,
     as with the Silic8 category card and the Warmshell system cards. A blurb that
     repeats its item's own page remains furniture: the X42 listing rule's reason,
     applied as stated.
   - **A callout** (the supplier finder) is content on the page that is its subject,
     and furniture elsewhere.
3. **Collection.** `data-src` images and `.docx` links are collected after their sizes
   are measured and shown. DOCX is read by Docling's DOCX backend into the same element
   model. The 3 gov.uk PDFs are read. Each reader keeps its own fingerprint, so no PDF
   reading is redone.
3a. **Word documents, layout- and image-aware** (the user, 1 October). The 8
   declarations have no heading styles. Their layout is tables (two with merged cells),
   bold lines and embedded images: the CE mark in 7, a signature in 7. A DOCX has no
   fixed page geometry: Word lays it out when it is opened. So "as a visitor sees it"
   means rendered.
   - **Truth `docx-pages`.** All 8 documents, rendered by LibreOffice 26.2.6 (MPL-2.0;
     unpacked into the git-ignored `tools/`, no system install) to PDF, every page
     judged from its image as X8's truth was. The truth records the text, headings,
     table cells with their row and column headers, and the images with their words.
   - **Arms:**
     - (a) Docling's Word reader: headings from short bold lines, tables from the
       file's grid, images extracted.
     - (b) LibreOffice's PDF read by the measured PDF pipeline (Docling with GLM-OCR
       table structure, visibility, figures cropped).
   - **Rule:** X8's bars (text recall ≥ 0.99, numbers 1.000, table values placed
     ≥ 0.95). Among passing arms, the better on table values; a tie goes to (b), the
     one pipeline for all documents.
   - **As judged (before any arm runs):** 12 pages.
     - The truth holds every visible line in reading order and 57 label-value pairs.
       The declarations set values beside labels inside ruled boxes, so pairs are
       scored as X8 scores them: the value is in its label's unit or the next.
     - It holds 18 rows of ruled grids (two mortar tables without a header row, one
       three-column table with one).
     - It holds 15 images: 11 CE marks and 4 signatures. "Captured" means a figure
       element on that page. Image recall is reported, and must reach 1.0 for the
       reading to count as image-aware. A signature carries no printed text, so it is
       a picture passage only.
     - Headings: each page's title or numbered heading, recall reported.
   - A citation opens the online `.docx` at its plain address: a Word file has no
     page fragment.
3b. **Images the pages show without an `<img>` tag.** 41 blog banners are CSS
   backgrounds. Their files are collected with the rest. Inline SVGs (one per page:
   icons and the logo) are furniture.
4. **Embedding reuse.** A build takes a stored vector when a passage's embedded text and
   embedder are unchanged. No vector changes value, so this is checked by building
   version 17's passages again and comparing every vector.

## B. Images

**Every image, every source** (the user: "everything multimodal so we aren't missing a
single evidence or context"). The same treatment covers every picture:
- the site's images, including lazy-loaded ones and CSS backgrounds;
- PDF figures, and the 8 low-text PDF pages;
- images embedded in the Word declarations.

Each picture is indexed by:
- its own words: alt text, caption, and text inside it (OCR, gated in B2);
- a vision model's description, searched but never quoted (B3's arm T+D);
- the picture itself, given to the generator when retrieved (B4–B5).

The one known gap is video. The 5 YouTube videos keep only their titles and the text
around them: their captions can be downloaded only with the owner's authorisation
(YouTube Data API `captions.download`).

**Image passages.**
- Images come from web pages and from PDF figures, cropped by pdfium at their box.
- Figures under 72 pt on a side are skipped, and so are images that appear in 3 or more
  documents (logos).
- Each image is stored once as a PNG of at most 1,024 px. llama.cpp's loader does not
  read WebP, which is 239 of the 380 site images.
- An image gives one passage per source of its own words: its alt text (5 words or
  more), its caption, and the text inside it (OCR, below). Short alt text and its
  section path are context: searched, never quoted.
- A web image's citation opens its page; a figure's opens `#page=N`. The picture is
  served by the API and shown beside the claim.

**B2. Text inside images: the OCR gate.**
- Set `image-text`, registered before OCR runs on it. It holds 40 images that carry
  text, drawn with seed 43:
  - 20 site images (pack shots, charts, banners with words), drawn per image folder;
  - 20 PDF figures (charts, diagrams, labelled drawings), drawn per document format.
- Each image's text is transcribed by reading the image, as X8's truth was.
- **How the 40 are chosen** (fixed before OCR runs on any image; written while
  looking through the candidates, `evaluation image-candidates --seed 43 --count 100`):
  - Candidates are taken in drawing order: site images first, then PDF figures.
  - An image qualifies when it carries printed words and every word on it can be
    read, enlarging the original file if needed. An image with any word cut off,
    obscured or too small to read is skipped and its reason recorded. These include a
    watermark, an inscription cut at the frame, and fine print on a tin's side.
  - A figure repeating a picture already chosen (the same logo or illustration in
    another document) is skipped.
  - Transcription takes every word in reading order: lines of a pack shot, labels of
    a drawing, a table's cells row by row. Words are compared as W2 compares them
    (case and punctuation folded).
  - A first pass showed that transparent site images (white icons and lettering)
    vanished on a white ground. `images.normalised` now lays a light drawing on dark
    grey before any image was chosen.
- GLM-OCR transcribes each image (the X8 configuration).
- Bars: word recall ≥ 0.95 and precision ≥ 0.98 over the set, as X8.
- Passing, OCR text enters as passages labelled "read from the image". An OCR passage is
  kept only if at least 20% of its words are not already in its page's text.
- Failing, OCR is not used. The failures are recorded per kind, and a kind that passes
  on its own may be adopted alone.

**B3. Finding images: retrieval arms.**
- Set `image-facts`: one question per image passage of the `image-text` images and of
  52 descriptive alt texts. Each is asked by its page or document title and section
  path (as `web-facts`), with the image's own words as evidence. Built and registered
  before any arm.
- Arms:
  - T: text only (alt text, caption, OCR text, context).
  - T+S: T fused by RRF with a SigLIP2 so400m text-to-image ranking. SigLIP2 runs on the
    CPU and is already in `models/`; UniDoc-Bench reports that fusing text and image
    rankings beats either alone and beats joint embeddings.
  - T+D: T with a vision model's description of each image as search-only context,
    never quoted or shown.
- Rule: the arm with the highest Success@8 whose interval against T (images resampled)
  lies above zero; otherwise T.

**B4. The generators see images.**
- The F16 projectors of the two generators are downloaded (Qwen3.6 899 MB, Gemma 4 26B
  1,193 MB; SHA-256 checked) and recorded in `models.json`.
- Serving check for each, with 8081 stopped: `--mmproj --no-mmproj-offload`, GPU and RAM
  peaks, seconds per image, and a crash test of 20 requests with images (llama.cpp
  #26981 reports a Gemma 4 projector crash on CUDA).
- A generator passes if all 20 requests complete, peak GPU stays within 7.4 GB, and
  answers without images are byte-identical to the server started without the
  projector.
- Up to 4 retrieved images per request, as PNG.

**B5. Two evidence modes, both measured.**
- **Text in images:** claims quote an image's own words, verified as every quote is.
- **Picture claims** (only with `LIMESPEC_PICTURES=1`):
  - A claim of kind "picture" cites an attached image and states only what it visibly
    shows.
  - Verification checks that the image was attached. The price, number and regulation
    checks still apply, so a picture claim can name no number or regulation the
    passages do not.
  - It is shown, marked "from the image", beside the picture.
- **Keep or cut, decided on E's run.** Picture claims stay only if both hold on the
  image strata (v6's image cases and conv-v1's image turns):
  - their risk (wrong answers ÷ answers given, by case) has a Wilson 95% upper bound of
    at most 5%;
  - coverage rises over the text-in-image arm, with its interval above zero.
- **Rung 2:** if the risk bar fails but coverage rises, the other generator checks each
  picture claim against the image (yes or no). The rule is applied once more.
- **Otherwise** the picture-claim code is removed. The report then records that claims
  from pictures need training data from the company.

## C. Index 18 and its gates

- **Index 18:** the web in W3's form; images in B's adopted forms; DOCX; OGL guidance;
  the PDFs, price fence and compiled lists unchanged.
- **It serves nothing until every gate passes:**
  - replay reach on v4, frozen90, v2 and v3 not below version 17 by more than 1 part
    per set;
  - `x9-tables` unchanged within 1 lookup;
  - `web-facts` and `image-facts` not below their arm results;
  - `exposure-v1` unchanged;
  - guardrails pass (no price shown, every emergency referred);
  - `web-links` reports zero problems.

## D. Evaluation sets covering every data type

**`heldout-v6`**, written by an outside model family in a fresh thread, relayed by the
user. The writer sees each source as a visitor sees it, never this pipeline's output:
- pages: Chromium's visible text and a screenshot;
- PDFs: page images and their text;
- DOCX: its text;
- images: the files and their alt text.

**Strata**, each with at least 6 cases:
- data type:
  - the 6 page formats and the 6 PDF formats;
  - PDF tables, PDF figures and charts;
  - DOCX, OGL guidance;
  - images with text, images without text;
  - cross-type (a page with its PDF or image);
- question type: simple, condition, list, comparison, multi-part, structure (where a
  heading path decides the answer), visual, absent, false premise, price, emergency,
  injection, out-of-domain.

**Size:** about 220 cases (about 180 answerable, 30 to refuse, 10 emergencies). Each has
one wording, and a third get a rushed second wording.

**Evidence kinds:**
- `page_text`;
- `pdf_text` (with its page);
- `docx_text`;
- `image_text` (alt text, caption, text in the image);
- `image_visual` (the picture alone; its expected answer is graded with the image in
  view).

**Checks:**
- `check-cases` gains these kinds.
- Quotes are checked against the rendering (pages), the text layer (PDFs), the DOCX text
  and the image's alt text or transcription.
- `reach` credits `image_text` and `docx_text`.

The set is sealed and registered before any arm answers it.

## E. The all-pairs run

- **Arms:**
  - index 17 against index 18, each with Qwen3.6 and with Gemma 4 26B, text path;
  - on the image strata and conv-v1's 19 image turns, each generator also "sees images,
    text claims" and "sees images, picture claims".
- **Sets:** frozen90, v2, v3, v4, v6, conv-v1 first turns.
- **Grading:**
  - blind; every v6 answer, and on the older sets the answers that differ between arms;
  - a sample goes to two outside graders (κ ≥ 0.8 each, else the guide is sharpened and
    the sample regraded, as R0);
  - readout per stratum: risk, coverage, refusals, safety.
- **It decides:** the index, the generator, and whether picture claims stay (B5).
- **Then:** `v5-candidate-2` is frozen, v5's web quotes are checked against the new text
  by case id, and v5 runs last.

## Results

*(added step by step)*

**B2, the OCR gate: passed** (`image-text` sealed in `e482dfe` before any OCR;
`data/runs/x43/ocr-glm.json`). GLM-OCR ran on the CPU, so no other model server had
to stop: about 12 s per image, 8 minutes for the 40.

| Source | Word recall | Precision |
|---|---|---|
| All 40 images | **0.971** | **0.998** |
| 20 site images | 0.949 | 1.000 |
| 20 PDF figures | 0.988 | 0.996 |

Every miss is one of three kinds:
- **Rotated text.** The vertical text on two bags' spines was not read (Solo, Ultra).
- **One word broken across two lines.** "boundari / es" in an EPD table was read as
  "boundaries".
- **One misread word.** "Recovery" was read as "recovering", plus one "MND" dropped.

No word was invented. OCR text is adopted as image passages, labelled "read from the
image". Rotated print stays a known gap.

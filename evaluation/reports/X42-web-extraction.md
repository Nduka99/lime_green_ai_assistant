# X42. Web pages: extraction measured against what the page shows

Design and rules written on 1 October 2026, before any arm is scored (plan approved the
same day; the v5 gate run was stopped and discarded first, E6).

## Question

The corpus is one web corpus: the site's pages and the PDFs they link. PDF reading was
scored against sealed ground truth three times (X8), checked for text a reader cannot
see (D86, D87) and given a measured passage form (X9). Web pages were never scored: the
extractor (`ingest.extract_sections`) dates from the submission. Does it read what a
visitor sees, in the right structure, and do its passages serve retrieval? Where not, what
general change fixes it?

## The audit before any change (read-only, 160 cached pages)

| Area | Finding |
|---|---|
| Coverage | 160 of 164 sitemap URLs (missing: two looping news pages, About Warmshell, the register page); 15 product pages embed an NBS spec widget (iframe), 4 a YouTube video, neither in the corpus |
| Text | 998 of 63,692 shown words (1.6%) not extracted, counted as a bag of words (W0's instrument: the main content with the furniture removed, a knowledge-base title block's label and date counted as shown). Words the extractor adds (glued across inline tags) cannot be told apart from the title repeated as a section heading in a bag of words, so precision is left to W2 |
| Structure | only the nearest heading is kept, so on the 18 pages with two or more heading levels below the title a passage loses its parent heading; web passages carry no context, PDF passages carry a section path |
| Passages | 824 web passages, median 240 characters; 303 (37%) hold under 120 characters below their heading (colour pages 113, products 65, support 58); 225 (27%) repeat text found on another page |
| Furniture | removed by a selector list built by inspection; pages were never rendered |
| Links | PDF links open the online file at its page (`#page=N`), but paths with spaces are not percent-encoded; web links use text fragments built from the extracted text, never checked against the page as shown |
| Images | alt text and captions are not indexed |

## Steps and rules

**W0, the audit as code.** `evaluation web-audit` computes, per page and in total: words
not extracted, heading levels used, passages, passages under 120 characters
of body, and passages whose body repeats on another page. Its first run is the baseline.

**W1, ground truth.**
- **Sample, seed 42, 30 pages.**
  - First, 8 pages drawn from the structure-rich pool: pages with nested headings, a
    definition list or a table.
  - Then the rest drawn per page type to these totals (the 8 counting towards their
    types): product or system 8, colour 4, knowledge base 6, case study 4, news 3, other
    5 (home, category, FAQ, terms, contact and similar).
  - The draw is committed code (`evaluation web-sample`).
- **Rendering.** Each page is drawn by headless Chromium (Playwright) at 1,280 px wide,
  from the cached HTML, with the site's own CSS, fonts and images. Third-party requests
  (analytics, video, the NBS widget) are blocked. Kept per page: a full-page screenshot
  and the visible text (`innerText`).
- **Truth.** Judged per page by the primary grader: the visible text gives the words, the
  screenshot gives the structure. Recorded:
  - the title;
  - the main content's blocks in reading order, each a paragraph, list, table or image
    with a descriptive alt text, with its words and its section path (the visible headings
    above it, outermost first);
  - each heading with its level;
  - what is furniture.

  No extractor's output is consulted while judging. The set is registered as `web-pages`
  before any arm is scored.

**W2, extractors.**
- **Arms:**
  - (a) the current extractor;
  - (b) Docling's HTML backend, giving the same element model as the PDFs, then passages
    by `passages.py`;
  - (c) trafilatura.
- **Measures, per page and in total:**
  - text recall: truth content words found in the arm's text, as multisets;
  - precision: the arm's words found in the truth content;
  - heading recall;
  - section-path accuracy: the share of truth blocks whose words fall in a passage whose
    heading and context contain every heading of the block's section path;
  - list integrity: truth lists whose items all appear, in order, in one passage;
  - table cells found in one passage with their row label and column header;
  - descriptive alt texts captured.
- **Rule:** an arm qualifies with recall ≥ 0.99, precision ≥ 0.98 and list integrity not
  below (a). Among qualifying arms the highest section-path accuracy wins; a tie within
  0.01 goes to an arm already installed, then the simpler. If none qualifies, the failures
  are diagnosed and the best arm gets a general structural fix, scored again on W1.

**W3, the web passage form.**
- **Set:** `web-facts`, one question per truth fact of W1 (a sentence, list or table cell
  that answers something), built and registered before any arm, as `x9-tables` was
  built from X8's truth.
- **Arms:**
  - the current form;
  - page-sized passages with a section-path context (X9's form for PDFs);
  - the same with text repeated across pages kept once.
- **Rule:** the highest Success@8, with its interval above the current form's (cases
  resampled); otherwise the simplest.

**W4, links.**
- Every source link is an online address with its path percent-encoded; PDFs keep
  `#page=N`.
- A web link's text fragment must match the page as rendered, or the plain page address
  is used.
- Checked by tests, and over every answer of the G3 runs.

**W5, content not collected.** For the NBS widget, its terms and content are read before
any collection (the user's decision). Descriptive alt texts become image passages only if
conv-v1's image turns show the value. YouTube is out of scope.

**W6, regressions before a new freeze.**
- Index version 18 = the web side by W2 and W3; PDFs, the price fence and the compiled
  lists unchanged.
- **Gates:**
  - replays on held-out v4, frozen90, v2 and v3 (reach not below version 17 by more than
    1 part per set);
  - `x9-tables` unchanged;
  - `exposure-v1`;
  - guardrails;
  - `web-facts` improved.
- **Then:**
  - a new freeze (`v5-candidate-2`);
  - `check-cases` on v5's web quotes against the new text, by case id;
  - v5 last.

## Results

*(added step by step)*

**W0 baseline** (`12c5404`, `data/runs/x42/audit.json`): 63,692 shown words, 998 not
extracted (1.6%); 824 passages, 303 under 120 characters of body, 225 repeating another
page's text; 18 pages with two or more heading levels below the title. The W1 sample
(seed 42) holds knowledge 6, news 3, case study 4, product 8, colour 4, other 5.

**Amendment to W1's rendering, before any truth was judged.** A first probe drew a blank
page with only the cookie notice: the site's own scripts load jQuery and GSAP
ScrollTrigger from public CDNs and fonts from fonts.net, and with every third-party host
blocked, the content stayed at its starting state, invisible until revealed by script.
The rendering now loads what a visitor's browser loads (the site's assets, the libraries
and fonts its pages name). It blocks only trackers and embedded widgets: analytics,
reCAPTCHA, YouTube, the NBS widget. It then dismisses the cookie notice ("Essential
only") and scrolls through the page so that scroll-triggered content appears. The probe
page then shows its full content, title-block date, sidebar and footer.

**What counts as main content (fixed before any page is judged).**
- **Main content** is what a visitor reads about the page's own subject:
  - the title, and the title block's label and date;
  - the body text, lists and tables;
  - on a product page, its own uses, the colours it comes in, and the names of its own
    downloadable documents.
- **Furniture** is what the site repeats on many pages or what only points elsewhere:
  - the header, menus and colour pickers in the menu;
  - breadcrumbs and tab labels;
  - generic help and supplier boxes;
  - cards for related products, case studies and articles;
  - gallery prompts, link buttons ("More products >", "Read case study >") and the
    footer.
- **Recording.** The truth is written as an outline over the numbered lines of the
  rendered visible text: the title, title-block lines, headings with their visual levels
  (the title is level 1), paragraphs, lists, table rows, and descriptive alt texts (from
  the HTML, five words or more). Lines left out are furniture. `evaluation web-truth`
  turns the outlines into blocks, each with its section path.

**Clarifications made while judging, each applied to every page (before any arm).**
- **Listings.** On a page that lists other pages (a category, a colour, the news index,
  a system's products), the names of the items listed are content, as one list. Each
  card's blurb and link are furniture: the blurbs repeat the item's own page, and the
  colour pages, judged first, had been recorded this way. A case study's "Materials used
  in this project" cards stand in the sidebar beside the "More case studies" cards and
  are furniture.
- **Bold labels and kickers.** A bold line standing alone above the text it names is a
  heading at its visual level ("The Requirement", a numbered regulation clause, a
  question). A bold line ending in a colon that introduces a list is a paragraph. A small
  capitals label ("QUALITY ASSURED LIME PRODUCTS") is a heading when it is the only name
  of its section, and a paragraph when a heading follows it.
- **Closing paragraphs.** A conclusion that speaks for the whole article after its last
  section (the sales close, references, the "Education Guide" label) stands outside the
  last section (outline entry `end`). Paragraphs that continue the last section's topic
  stay in it.
- **Body sentences with links** ("Find your nearest stockist here") are content. Styled
  link buttons ("Vote Here >", "Read case study >") are furniture.

**Amendment to W1's rendering: answers behind an accordion (1 October, before the FAQ
page was judged).** The FAQ page's answers sit in a definition-list accordion that opens
one answer at a time, so the first rendering kept the questions and no answers. The
rendering now clicks each term whose answer is hidden, marks each answer that opens, and
then shows every marked answer, so the text holds each answer a visitor can open, in
place. Only answers that opened on a click are shown; nothing hidden by other means is
revealed (D86, D87). All 30 pages were rendered again. The visible text of the other 29
is byte for byte the same, so their outlines stand. Four of the 160 cached pages hold
definition lists: the FAQ, the glossary and two case studies.

**W1 truth** (registered as `web-pages`: 30 outlines, the 30 visible texts they number,
`truth.json`):
- 384 blocks: 315 paragraphs, 39 lists, 26 title-block lines, 4 descriptive alt texts.
- 145 headings below the titles (76 at level 2, 60 at level 3, 9 at level 4); 14 pages
  use two or more levels.
- 82 blocks sit under two or more headings, so their section path needs the parent
  heading.
- 13,046 content words, alt texts apart.
- No page holds a table (none of the 160 cached pages has an HTML table), so W2's table
  measure has nothing to score.

**W2 details, fixed before any arm is scored.**
- **Readings.** Each arm gives a page's reading: its title, its headings, and its
  sections in order. Each section has a path (the headings the arm records above it)
  and its texts.
  - (a) `ingest.extract_sections` as it stands. A section's path is its one heading,
    as its passages carry it.
  - (b) Docling's HTML backend (docling-core 2.99) reads the main content after the same
    furniture removal as (a). On its own it reads the whole body, the site's menus
    included (probe on a product page: every menu card came out as a title). Exported as
    Markdown.
  - (c) trafilatura 2.2.0 reads the whole page with its own content detection. Output
    as Markdown.
  - (b) and (c) go through one Markdown reader: a line of `#`s is a heading at that
    level, the first level-1 heading is the title, and paragraphs and list items are
    texts under the headings above them.
- **Words.** Unicode compatibility forms are folded, case is folded, and words are runs
  of letters and digits, so punctuation and typography do not count. Recall and
  precision use word multisets per page, summed over pages. An arm's word counts as
  right for precision when the truth holds it, in its content or its alt texts.
- **Section-path accuracy is measured on each arm's sections, not its passages.** The
  design said "a passage whose heading and context". Passages pack several sections
  (W3's subject), and a packed passage shows its later sections' headings in its text,
  not its context.
  - The tested blocks are truth paragraphs and lists with at least one heading above
    them; a block with none tests nothing.
  - A block's holder is the section whose text holds the block's text, comparing letters
    and digits only. Failing that, it is the section sharing most of the block's words.
  - The block is placed right when every heading in its path equals, by the same
    comparison, a heading in the holder's path.
- **Other measures.** List integrity: every item, in order, in one section. Heading
  recall: truth headings equal to one of the arm's headings, the title apart. Alt texts:
  inside the arm's text.

**W2 result (`b747c8b`, `data/runs/x42/w2-<arm>.json`): no arm qualifies.**

| Arm | Recall | Precision | Headings | Section paths | Lists | Alt texts |
|---|---|---|---|---|---|---|
| (a) current | 0.964 | 0.935 | 0.579 | 0.518 | 0.538 | 0 / 4 |
| (b) Docling HTML | 0.971 | 0.866 | 0.228 | 0.322 | 0.487 | 4 / 4 |
| (c) trafilatura | 0.959 | 0.904 | 0.221 | 0.212 | 0.564 | 0 / 4 |

Neither generic reader knows the site's headings: most are paragraphs styled by class
(`p.h3-style`) or bold lines, which both read as text. (a) reads the classes, so it leads
on structure. By the rule, (a)'s failures are diagnosed and (a) gets the fix.

**Diagnosis of (a), by mechanism** (per page, `x42_diagnose.py`):
- **Only the nearest heading is kept.** No FAQ answer keeps its category (0 of 37). A
  heading with no text directly under it vanishes from the reading, as every FAQ
  category and each colour page's "Products available in …" heading do.
- **Bold lines are read as paragraphs** (E5 A′). That holds for the case studies'
  "The Requirement" headings, the knowledge base's question subheadings and the sensor
  headings S1–S4: 33 headings in all.
- **Leaf-only reading loses text.** A block element whose text sits outside the tags
  listed (a `<blockquote>` with bare text, text after a `<p>` inside an `<li>`) loses it:
  76 words of one article, a sentence of another.
- **Over-broad furniture selectors remove content.** `.swatch` holds colour names and
  document names, `.portal` the team and the Warmshell benefits, `.blog-feed` the news
  index's article names. The title-block label and date and image captions are lost too.
- **Furniture kept.** Listing cards' blurbs (100 to 200 words per listing page), the
  case-study sidebar's "Materials used" cards, back links, link buttons, the supplier
  and technical callouts, and the FAQ's AI box.

**The fix (designed from W1's failures; research below).**
- **Block reading like a browser's.** Text is broken into lines at block-level element
  boundaries and at `<br>`, and joined inside inline elements. This follows the WHATWG
  `innerText` algorithm ("rendered text collection": a block-level box starts and ends
  a line), as Inscriptis does for layout-aware HTML to text (Weichselbraun 2021, JOSS).
  No text is lost because its tag is not on a list.
- **Headings with levels and a path.** `h1`–`h6` by tag. A paragraph styled `hN-style`
  takes level N (the site's way of marking headings). A definition term, or a bold line
  that is not followed by a list and fits on one line of the content column (100
  characters), sits one level below the last tagged heading. Every element records the
  path of headings above it. A heading with no text of its own stays in the path.
  - Bold or large text acting as a heading without heading markup is a known pattern
    (WCAG failure F2). WAVE's "possible heading" check treats short bold or large text
    as a probable heading.
- **Components by role, from the main-content rule.**
  - Furniture is removed: carousels, the case-study sidebar boxes, highlight sections,
    callouts, back links and link buttons.
  - A card that is not a link carries content and is kept, its title read as text.
  - Link cards left in the page's own column are its listing, read as one list of their
    names. Colour grids and download buttons are read the same way.
  - The title block keeps its label and date as text; its `<h1>` is the title.
- **Considered and not used:** site template detection (blocks repeated across a site's
  pages are boilerplate; Bar-Yossef and Rajagopalan 2002). Here the FAQ repeats a
  knowledge-base paragraph word for word, so it would delete content. Repeated content
  is W3's question (passages kept once).

**The fix as built and frozen** (`src/limespec/webpage.py`, arm `fixed`), with two
changes made while iterating on W1:
- **The lead-in test.** It went from "followed by a list" to "ending in a colon or
  semicolon", as the judging rule states it. "The Problem", followed directly by its
  list, had been read as a lead-in.
- **Large text.** The site's large-text class (`page-lead`) is treated like bold: short,
  it is a label ("Downloads", Q&A questions); long, it is a lead paragraph.
- **One furniture selector added.** The product pages' "Product advice and expert help"
  box (`.call`, which holds only that box on all 160 pages).

| Arm | Recall | Precision | Headings | Section paths | Lists | Alt texts |
|---|---|---|---|---|---|---|
| (a) current | 0.964 | 0.935 | 0.579 | 0.518 | 0.538 | 0 / 4 |
| (a) fixed, on W1 | 1.000 | 0.993 | 0.986 | 0.967 | 1.000 | 4 / 4 |

On W1 the fix qualifies. Its residual misses:
- the about page's kicker labels, which the reader places under the large statement
  that follows them;
- one sentence repeated under two headings, which the scorer assigns to the first;
- furniture without a component of its own: the colour pages' inline samples box, the
  Warmshell cards' titles that CSS hides, a copyright line, one hero image's alt text
  (a judging slip: the products page's hero alt was not recorded).

These W1 figures were reached by iterating on W1. The held-out pages decide.

**W2b, pages the fix was not derived from (fixed before the fix is written).** Ten new
pages are drawn with seed 43 from the 130 pages outside W1: product 3, colour 1,
knowledge base 2, case study 1, news 1, other 2. They are rendered and judged by the same
rules, and registered as `web-pages-holdout`, before the fixed reader exists. The fix is
kept only if it qualifies on W1 and holds on W2b: recall ≥ 0.99, precision ≥ 0.98, and
section-path accuracy and list integrity not below (a)'s on W2b.

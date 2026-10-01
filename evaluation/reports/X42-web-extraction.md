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
not extracted, glued words, heading levels used, passages, passages under 120 characters
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

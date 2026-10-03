# 0030. Search channels after X44: company content, pictures and guidance ranked apart

- Status: Accepted for the next index; version 25 serves nothing until X45 closes the
  gates it misses (below)
- Date: 2026-10-02
- Origin: X44 (`evaluation/reports/X44-pre-generation.md`), after X43's version 21
  failed its index gates

## Context

Version 21 put every data type into one search: pages, Lime Green's PDFs, Word
declarations, GOV.UK guidance and 539 pictures. It lost web facts it had held (0.969 →
0.932). Two kinds of passage displaced the right one:
- picture passages, most with no words of their own but their page's title;
- general guidance, which outranked the company's own pages.

Its v3 and v4 losses were mostly the scorer: evidence was matched against a passage's
text alone, while the model reads its title and section too.

## Decision

- **Evidence is matched as the model reads it** (title, section, text) in every scorer.
- **Each passage has a search channel** (migration `20261001200000_search_channels`):
  - `company`: the site's pages and Lime Green's documents fill a search's 8 places, as
    before;
  - `picture`: each search adds its 2 best pictures by their own words, then its 2 best
    by what they show (SigLIP2 so400m, text tower on the CPU), at most 4 per question.
    Each retriever keeps its own places, as UniDoc-Bench splits its results; one fused
    ranking did worse (amendment 1);
  - `guidance` (GOV.UK, titled with its publisher): at most 2 passages, added only where
    the reranker places them above the company's last place.
- **A picture's citation** opens its page, or its document at the page, with no text
  fragment: its words are not the page's text.
- **Web reading:**
  - a link card's description is read where no other page of the site holds it (two
    passes at build time);
  - a slideshow of text slides is content, while a slideshow of link cards is not.
- **PDF passages:** a number range broken across lines after its hyphen gets the
  hyphen back. Three numbers were corrupted ("EN 13501-1" read as "135011").
- **OCR:** markup-only OCR replies are no text.
- **Scope:** the 25-Year Environment Plan leaves the index (the user).
- **Not adopted:**
  - picture descriptions by a vision model (F6): 63 against 62 of 76 picture questions;
  - descriptions in the compiled lists (F3b): it lost 3 parts on v2;
  - the fused picture ranking.

## Measured (version 25 with these decisions)

| Gate | Bar | Result |
|---|---|---|
| G1 replays (frozen90, v2, v3, v4) | not below version 17 by more than 1 | 108, 83, 78, 118: pass |
| G2 `web-facts` | not below version 19 | 0.966 vs 0.969 (−0.003 [−0.009, +0.000]): pass |
| G3 `x9-tables` | within 1 lookup | 0.980 vs 0.978: pass |
| G4 `image-facts` | ≥ 0.850 | 0.825: **fails by one question** |
| G5 `kb-probe` | text ≥ 0.90, pictures ≥ 0.75, guidance ≥ 0.80, no stratum below 17 | text 0.841, pictures 0.700, guidance 1.00; web content one below 17: **fails** |
| G6 `web-links` | 0 problems | 0: pass |
| G7 cost | p95 ≤ 1.5 s, ≥ 6 GB free | p95 1.77 s, process 3.4 GB, 8.2 GB free: **fails on time** |

## Consequences

- Version 25 is the best index so far, but it serves nothing until X45 passes G4, G5
  and G7.
- **X45 addresses the measured causes:**
  - **extraction:**
    - the site footer's facts (opening hours, phone, address) are in no page;
    - the colour-sample cards' "Free";
    - two Word declarations, where Docling joins a value to the next row's label;
  - **the list arm:** compiled descriptions as well as the unique ones (F3b gained 11
    parts on v3);
  - **picture places:** where pictures still fail;
  - **search time:** the channels run one after another.
- `kb-probe`'s extraction misses were found on that set itself, so X45 checks their
  fixes on other sets as well.
- The API now needs torch and transformers for SigLIP2's text tower (CPU wheels, 2.7 GB
  of RAM).

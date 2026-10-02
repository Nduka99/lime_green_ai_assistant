# 0032. Retrieval frozen for E: per-channel keyword indexes and a search per thing asked

- Status: Accepted. Retrieval is frozen for E; no further retrieval round before
  deployment (the user, 2 October).
- Date: 2026-10-02
- Origin: X47's data-type ladder and X48's final run
  (`evaluation/reports/X47-document-relevance.md`, `X48-final-run.md`)

## Context

- **X47's ladder** added one data type per build from version 17 and kept the web reader,
  Word files and GOV.UK guidance by its rule.
  - Pictures failed on v2 (−4). The cause was not the pictures: each version had one BM25
    index over all its passages. Adding guidance or pictures changed the company's
    keyword statistics, and one About-page passage crossed the company's 8th place
    (+3, then −4).
- **The question-type routes** the user named (compiled descriptions for list parts,
  guidance for regulation parts, pictures for visual parts) were measured before any
  was built. Their ceilings were +4, 0 and 0 parts.
- **The room was elsewhere.** Multi-part questions kept as one search reached 0.67 of
  their parts, against 0.82 when split.
- **The user asked for one final run**, then E and deployment.

## Decision

- **One BM25 index per channel** (`passages_bm25_v<id>_<channel>`; `add3aaf`).
  - Company, guidance and picture passages each score words against their own
    statistics, so no channel can move another's keyword scores.
  - Versions built earlier get the indexes with `limespec keyword-index --version N`.
  - The registered identity check failed on 2 of 264 questions, by tie order alone: the
    tied scores are identical, and passage ids follow build order. The user kept the
    indexes on that evidence.
- **Items** (`a0aca58`).
  - The first request gives each search question its items: when it covers several
    things, each is written as a search question naming its subject.
  - Each item's search adds its best 4 passages not yet given, then its scoped search,
    within the budget of 32. Nothing is removed (`config.ITEM_SEARCHES` on).
- **E4 (compiled descriptions) stays everywhere.** Even with every part searched alone it
  adds 12 parts, on list questions that name no items.
- **Cut, from the measurements:** the list, guidance and picture routes. The X47
  document-relevance arms are deferred until after deployment; nothing is removed.
- **The frozen index:** version 28 (web reader, Word, GOV.UK channel, pictures channel,
  E4) with per-channel indexes. The generator is Gemma 4 26B-A4B (ADR 0029).

## Measured (version 28, per-channel indexes, the four development replays)

| | frozen90 | v2 | v3 | v4 | Sum (of 486 in the version) |
|---|---|---|---|---|---|
| Before X48 (shared index, Qwen's search questions) | 111 | 80 | 88 | 121 | 400 |
| Gemma's search questions | 112 | 83 | 89 | 119 | 403 |
| **Gemma's search questions + item searches (frozen)** | 112 | 89 | 89 | 121 | **411** |

- **Unchanged against version 28:**
  - `web-facts` 0.955 (+0.003 [+0.000, +0.009]);
  - `image-facts` 0.825;
  - `picture-probe` 0.938 and `picture-probe-2` 0.875;
  - `kb-probe` text 0.864, pictures 0.700, guidance 6/6.
- **Search p95** is 1.35 s for a single search. The replay's per-question search p95 is
  9.68 s against 8.13 s without items. The replay harness gives the main and scoped
  searches no shared cache, so this overstates an answer's search time.

## Consequences

- **E runs on this path with v6 as the main set, then v5.** Nothing in retrieval changes
  before deployment.
- **Known limits accepted:**
  - 75 of the 486 parts in the version still do not reach the model on these sets;
  - `image-facts` is 0.825 (bar 0.850): wordless drawings beyond each retriever's first 2;
  - the Word declarations' fire and strength classes;
  - a look-alike safety data sheet;
  - short facts diluted inside long page-form sections (the About page).
- **The oracle split** (472 of 486) was written with the key's knowledge of the evidence.
  It is an upper bound, not a target.
- **A rule comparing result order must allow exact ties**, whose order follows passage
  ids and so the build.

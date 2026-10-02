# X48. The final retrieval run

Rules written on 2 October 2026, before any step of the run. The user asked for one
final multi-arm run that settles retrieval, then E on v6 and deployment: "I will settle
on whatever is left" (D118). The decision follows the rules below with no re-run.

## Why these two changes, and what was cut

Measured before planning, from the version 28 and 29 replays (`data/runs/x45/`) and an
oracle split (`data/runs/x48/oracle-split-*.json`, each keyed part searched alone):

| Change | Ceiling over version 28's 400 parts (of 486 in the version) | Decision |
|---|---|---|
| E4 only for list parts | +4, all in v2 | Cut: about +3 after a real labeller's misses, at the noise bar |
| Guidance only for regulation parts | 0: no keyed part has GOV.UK evidence; `kb-probe` guidance already 6/6 | Cut |
| Pictures first for visual parts | 0 measurable: the picture sets search once per question | Cut |
| **A search per thing a part asks about** | **+72** (today's searches and the split ones together: 472) | **Built** |
| E4 everywhere, once parts are split | Version 28 against 29: 472 against 460 (v3 +10, v4 +2) | **Kept** |

- **Where the misses are.** Multi-part questions the first request kept as one search
  reach 122 of 182 parts (0.67); split ones 173/210 (0.82); one-part questions 105/108.
- **v4's oracle split falls**, 121 → 108. Its key writes parts as labels without the
  product ("Sack and bulk-bag sizes"), and such a search loses its subject: the
  lost-in-retrieval effect (ACL 2025).
  - So each item names its subject, and the part's own search always stays: an item only
    adds.
- **The X47 document-relevance arms are deferred** until after deployment. Nothing is
  removed.
- **Research** (sources in D118's chat): question decomposition with reranking (ACL SRW
  2025, +4.4 points Hits@4); comparison sub-questions each inherit one named entity;
  Adaptive-RAG and UniversalRAG (route only where an oracle shows room); RAGRouter-Bench
  (real routers capture about 80% of the oracle); pg_textsearch (a named partial index
  keeps its own corpus statistics).

## What was built

- **`add3aaf`: one BM25 index per channel.**
  - Each version has `passages_bm25_v<id>_<channel>` for company, guidance and picture.
  - Adding guidance or pictures can no longer move company keyword scores (X47 ladder:
    v2 +3, then −4, on one passage).
  - `limespec keyword-index --version N` adds the indexes to older versions.
- **`a0aca58`: items.**
  - The first request gives each search question its items: when it still covers
    several things (several products, or several facts about one product), each is
    written as a search question naming its subject (at most 6).
  - With `config.ITEM_SEARCHES` on, each item's search adds its best 4 passages not yet
    given, then its scoped search, within the budget of 32. Nothing is removed.
  - `ITEM_SEARCHES` is off until this run decides.

## The run (`data/runs/x48/final.log`; one detached script, each step with its own time limit)

1. **Per-channel indexes** added to versions 28, 29 and 31.
2. **Identity check.**
   - Version 29 (web reader, Word, GOV.UK, pictures) and version 31 (web reader and Word
     only) hold the same company passages.
   - With per-channel indexes, their company results must be identical, by passage text
     and order, for every question of the four replays.
   - Run with today's search questions (`data/runs/e5/replay-a2-e4-s-*.json`), scoped,
     no channels.
3. **P: version 28 with per-channel indexes**, today's search questions. Measured on:
   - the four replays;
   - `web-facts`, compared with version 28's file by `lookups.compare`;
   - `image-facts`, `picture-probe`, `picture-probe-2`;
   - `kb-probe`;
   - search time, 3 runs of 60 searches.
4. **Gemma writes the understanding once** (search questions and items) for the four
   replay sets.
   - Gemma 4 26B-A4B runs on 8083 in one slot (`-c 16384 -np 1`, E8 G3's line).
   - 8080 is stopped meanwhile: the user approved this on 2 October; the 8090 demo cannot
     answer during this step.
   - `start-servers.ps1` restores the servers afterwards.
5. **Arms A and B**, both on version 28 with per-channel indexes and Gemma's understanding
   fixed, replayed after the servers are restored, so their times are comparable:
   - **A:** without item searches.
   - **B:** with them (`--items`).

## Rules (applied by script to the run's files)

**The per-channel indexes stay only if all of these hold:**
- step 2's identity holds on every question;
- P's `kb-probe` keeps guidance at 6/6, pictures at 14/20 or more, and loses no text
  question that version 28 found (38/44);
- P's picture sets are not lower than version 28's: `image-facts` 0.825,
  `picture-probe` 0.938, `picture-probe-2` 0.875;
- P's `web-facts` difference from version 28 has a 95% interval whose upper end is ≥ 0;
- P's search p95 (median of the 3 runs) is ≤ 1.5 s.

Otherwise the shared index is kept, and the cause is reported.

**B is adopted (`ITEM_SEARCHES` on) only if all of these hold:**
- B's four replays sum to at least A's + 3;
- no replay set is below A's by more than 1 part;
- B's per-question search time p95 is at most A's + 2.0 s, about 10% of Gemma's 18.1 s
  median answer (ADR 0029);
- no question is given more than 32 passages.

Otherwise A is adopted.
- `kb-probe` and the picture sets score one search per question (`assistant.searched`),
  which items do not touch. So A and B are equal there by construction, and those sets
  are judged once, in P.

**Reported, with no bar:**
- of the questions with 2 or more keyed parts, the share Gemma searched as 2 or more parts
  or items, against today's (Qwen's) search questions;
- A against P, which is the generator's own splitting;
- A and B against today's 400.

## Deviations from the approved plan (stated before the run)

- **Gemma's understanding covers the four replay sets only.** `kb-probe` and the picture
  sets never use the first request.
- **8080 is stopped, not 8081.** Gemma does not fit on the GPU beside Qwen (7.2 of 8.2 GB
  in use). The user approved this.
- **The identity check compares versions 29 and 31.** Version 28 holds E4's compiled
  descriptions, which version 31 lacks.
- **A is replayed after Gemma stops**, from the understanding Gemma wrote, so that A and B
  are timed under the same conditions.

## After the run

- The winner is frozen for E and recorded in ADR 0032: version 28, per-channel or shared,
  with items or without.
- What is left is accepted, and no retrieval round follows.
- Next: E on v6, then v5, then deployment preparation.

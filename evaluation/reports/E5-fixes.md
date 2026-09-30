# E5. Fixes directed by attribution: from 9% wrong towards the 5% bar

Diagnosis, research, design and every acceptance rule written on 30 September 2026,
before any fix code and before held-out v5's key is read (the user approved the plan the
same day). Results are added below each stage as it is run.

## Question

The release bar R1 (`R0-reliability.md`) asks that, of the cases the assistant answers,
the share answered wrong has a 95% upper bound of at most 5%. On held-out v4 the
candidate (index version 12, C1 + C2) has 4 wrong of 43 answered (upper bound 21.6%).
Held-out v5 will have about 155–185 answered cases, which allows 2–3 wrong. What
general changes, chosen without tuning on any end-to-end run, bring the rate down?

## Diagnosis (measured on the S2b gate run's records)

| Stage | What goes wrong | Evidence |
|---|---|---|
| Index | A web list is cut between passages; its lead-in line is not a heading | v4 c47 (wrong in two arms). Site-wide: 7 of 48 lists split; 147 bold-only sub-headings on 56 of 160 pages are not read as headings |
| Index | The price fence hides a whole passage for one price in it | v4 c33 (wrong): the asked sentence sits in a fenced passage |
| Retrieval | Look-alike documents: 325 of 1,897 passages (17%) have text identical to another document's (safety data sheets, groups up to 31); the right product's copy ranks 50th–130th | v4 c01 (wrong), c02, c59 (refused): indexed, never in the top 20 |
| Generation | Missing evidence becomes a wrong answer: a nearby fact of the same kind is stated in the asked one's place | 9 of 10 substitution cases had no evidence for the asked part |
| Generation | A fact about another product merged into a list (v4 c10) | Evidence present; claims citing several documents are not wrong more often (8% against 12%) |
| Verification | Correct claims are removed | 65 removals in the gate runs: 23 quotes joined with "…" whose fragments are all in the cited passage; 8 quotes found in another given passage; 22 number removals where every number is in a given passage (17 are digits inside names) |
| No detector | No signal separates "evidence arrived" from "it did not" | The reranker's best score per search: AUC 0.72 on v4 (a threshold keeping 95% of covered questions catches 1 of 16 uncovered); three generator-as-judge checks failed in S2b |

Checked and not the cause: splitting questions further (a general splitting rule left
v4's reach at 0.838, raised v2 0.557 → 0.664, lowered v3 0.686 → 0.648 and frozen90
0.816 → 0.808); a bigger passage budget (12 → 32: no change on v4 and v3); showing
neighbouring passages (10 of 118 missed parts).

## Research

- Generators do not abstain on near-miss evidence when told to: twelve open models
  (135M–32B) still answer 40–99% of questions whose passages name the right things but
  lack the fact ([2609.37469](https://arxiv.org/abs/2609.37469)); small models answer
  42% of misleading-context questions ([2608.22228](https://arxiv.org/abs/2608.22228));
  any context lowers abstention ([2411.06037](https://arxiv.org/abs/2411.06037)).
- Relevance scores do not detect the gap (0.57 on near-misses in 2609.37469; 0.72
  here). The best published detector combines three small readers before generation
  (question components covered; an answer span found by a reader trained with a
  no-answer option; a small model judging the passages together): 0.84 on average,
  0.68 on the hardest near-misses.
- In look-alike corpora, restricting search to the right document family is the
  largest lever (precision 0.77 → 0.86, source identification 0.59 → 0.90), and
  multi-step loops add cost without accuracy
  ([2606.11350](https://arxiv.org/abs/2606.11350)).
- A threshold chosen on labelled calibration data bounds the error rate among answers
  given (conformal risk control); with a base rate μ above the target α, at least
  (μ − α)/(1 − α) of answers must be withheld even by a perfect detector: 4.5% here
  ([2606.29054](https://arxiv.org/abs/2606.29054)).
- Architectures surveyed: a single pass of hybrid search and a reranker matches or
  beats agentic pipelines at a third of the cost
  ([2601.07711](https://arxiv.org/abs/2601.07711)); with a local 7B model,
  self-reflection and answer verification made answers worse
  ([2606.21553](https://arxiv.org/abs/2606.21553)); graph retrieval wins on multi-hop
  questions and loses on single facts ([2502.11371](https://arxiv.org/abs/2502.11371));
  query rewriting is mixed ([2604.01733](https://arxiv.org/abs/2604.01733));
  fine-tuning for grounded refusal changes over-answering itself
  ([2409.11242](https://arxiv.org/abs/2409.11242)) but cannot be done on this machine.
  The architecture stays; scope and unit size at retrieval, a calibrated gate and
  verification change.

### Models for the stages besides the generator (cards read 30 September)

Limits: an 8 GB GPU already holding the generator (3.5 GB), the embedder (2.7 GB) and
the reranker (0.5 GB); about 14 GB of free RAM; llama.cpp for GGUF files, the CPU for
small encoders. Licences: Apache-2.0, MIT or CC-BY; non-commercial models are out
(jina-embeddings-v5, jina-reranker-v3 and v3.5, ctxl-rerank-v2, Provence, zerank-1,
Bespoke-MiniCheck-7B). Published scores come from different test beds and disagree
(Qwen3-Reranker-0.6B: 65.8 on its own card's table, 56.9 on another card's), so they
shortlist only.

| Stage | Now | Candidates | Published evidence |
|---|---|---|---|
| Embedding | Qwen3-Embedding-0.6B | Qwen3-Embedding-4B (Apache-2.0; held) first; then pplx-embed-context-v1-0.6B (MIT), DenseOn / LateOn (149M), harrier-oss-v1-0.6B (MIT) | Retrieval on MTEB English v2: 61.8 → 68.5 for the 4B model ([card](https://huggingface.co/Qwen/Qwen3-Embedding-4B)) |
| Reranker | bge-reranker-v2-m3 | Qwen3-Reranker-0.6B (Apache-2.0) first; Qwen3-Reranker-4B as the ceiling; then gte-reranker-modernbert-base (149M) | 57.0 → 65.8 → 69.8 on the Qwen card's table; instruction following 0.0 → 5.4 → 14.8 ([card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)) |
| Claim–question relevance | none | the instruction-following reranker scoring each claim against its part; OpenProvence (MIT, 149M), which keeps or drops each sentence for a question | the older reranker separated `relevance-dev`'s labels at AUC 0.89; OpenProvence keeps the answer sentence 93–94% of the time ([repository](https://github.com/hotchpotch/open_provence)) |
| Support check | quote, number and regulation rules | FactCG-DeBERTa-L (MIT, 0.4B); then MiniCheck (MIT) and the rule that two checkers must agree | 75.6 on [LLM-AggreFact](https://llm-aggrefact.github.io/), level with models a hundred times larger |
| PDF reading | Docling + GLM-OCR | none for now | newer parsers lead the public benchmark by 1–2 points, but on this corpus's sealed pages GLM-OCR placed 0.984 of table values (X8) and the index holds 124 of v4's 130 keyed parts |

Extraction models (GLiNER2, NuExtract 2.0), image and page retrieval models
(Qwen3-VL-Embedding-2B, ColQwen-class) and a monitoring judge (Granite Guardian) were
read and are left for their own stages: v5 asks no image question, and structured
extraction is needed only if smaller units win their test.

## Method

Every change is general and chosen offline, on a benchmark built from records already
held, by a rule written here before it is scored. No end-to-end run is used to choose
anything: the first full run is the v5 gate. If no candidate passes its rule, or an
error class survives its fix, the next step is a structured search of papers and
practitioner sources for that stage, recorded here, before another attempt.

## Stages and their rules

### D. Verification: stop the false removals

Candidate rules (`verify.check_claim`, `find_quote`): (1) a quote joined with "…" is
found when each fragment is found in the cited passage, in order; (2) a quote not in
its cited passage but found in another passage the model was given is cited to that
passage; (3) a number in a claim is supported when it appears in the cited passage's
title, heading or text together with the word it is attached to or follows in the
claim (a name such as "Silic8", "MPL1" or "ISO 9001"). The regulation check is not
changed.

**Benchmark `verify-dev`:** every distinct claim verification has removed in the audit
records of the evaluation runs (about 114: quote, number and regulation reasons), with
the passages the model was given. Each is labelled by reading, before any rule is
scored: **wrongly removed** (the passages given state the claim) or **rightly removed**.

**Rule:** a candidate rule is kept only if it restores wrongly removed claims and
restores **no** rightly removed one. Rules are scored one at a time and together.

*Built and labelled before any rule was scored (30 September):* `verify-dev` holds 177
answers drafted again from the audit records of every evaluation run whose checks
removed a claim (410 drafts, the same request drafted once), with **87 removed drafts,
76 labelled wrongly removed and 11 rightly removed**, each with its reason. The wrongly
removed: 29 quotes joined with "…" whose fragments are all in the cited passage, 27
digits inside names (Silic8, AD2, MPL1, ISO 9001, ISO 14001), 6 quotes word for word in
another given passage, 5 source markers the model wrote into its claim ("[S2]"), 5
"regs" read as Building Regulations, 4 numbers in the cited passage beside the quoted
words, 4 quotes that differ slightly from the passage, 2 claims whose other quotes
state them. The rightly removed: 3 "approved" where the passage says "works with" or
"unsuitable", 2 calling a standard "the regulation", 3 statements that the passages
lack something (one false), 1 price, 1 adding a product as recommended, 1 with numbers
in no passage. The current checks keep 0 of the 87. The rules as they will be scored:
(1) a quote containing "..." or "…" is found when its fragments are found in the cited
passage in order; (2) a quote not in its cited passage is cited to the first other
given passage that holds it; (3) a number missing from the quotes is supported when
the token it is joined to ("Silic8", "25kg"), or when it stands alone the word before
it and the number ("ISO 9001", "around 1"), is in the title, heading or text of a
cited passage.

### A. Index (version 13)

(1) A paragraph that is wholly bold and short is a sub-heading; a list stays in one
passage with its lead-in line when it fits (see Results for the two changes made when
this was built). (2) The price fence
removes the sentences that state a price, not the passage. (3) Each document records
its product scope: a product page and the files it links.

**Checks (structural, no tuning):** lists split across passages falls from 7 of 48
towards 0; every passage the fence kept out in version 12 appears without its price
sentences; `evaluation guardrails` on a replay (below) shows no price; passage counts
and the fingerprint are reported.

### B. Retrieval

(4) After each search, a second search inside the scope of the products the question
names (names from the site's own product pages, matched with spacing and hyphens
folded), else inside the scope of the best hits; an in-scope copy is kept when
identical texts compete. (5) Candidate: Qwen3-Reranker-0.6B in place of the current
reranker. (5b) Candidate: inside a product's scope, smaller units for technical
documents (first tested with X9's row-level index version). (5c) Second tier, only if
reach is still short: a questions-per-passage index.

**Benchmark: `evaluation replay`** re-runs the first request and the searches without
generating answers and scores evidence reached (`evaluation.reach`). It must first
reproduce the gate's reach on unchanged code (0.838 / 0.816 / 0.557 / 0.686 on v4 /
frozen90 / v2 / v3).

**Rule:** a retrieval change is kept if reach rises on v4 and falls on no set, the
passages given stay within the budget of 32, and `exposure-v1` is unchanged (the first
request is not touched). Changes are scored one at a time, then stacked.

*(4) as it will be built and scored, written before it is (30 September):* a passage's
scope is its title up to " — " (a PDF is titled after the product page linking it, so
no new column is needed); product names are the titles of the version's product pages;
a search query names a product when each of the name's words found in at most two
product names is in the query, spaces and hyphens ignored (`limespec.scope`). For each
search the question makes, a second search restricted to the named products' scope
adds its best 4 passages after the passages already gathered; a passage whose text is
already among them replaces that copy in place (the named product's own copy is
cited), and the total stays within 32. Questions naming no product are unchanged. The
fallback to the scope of the best hits is not built unless the named scope qualifies
and leaves missed parts it would reach. Scored by B's rule on the stage A index and on
the stack with the embedder that qualified.

**Model arms** (each a replay of all four sets with the baseline's search questions
kept, so arms differ only in the model): `r06` Qwen3-Reranker-0.6B in place of the
reranker; `e4` the index re-embedded with Qwen3-Embedding-4B (vectors cut to 1,024 and
normalised, so the schema stays); `e4-r06` both; `r4` Qwen3-Reranker-4B as the ceiling
on the better index. **Model rule:** an arm qualifies if reach rises on v4 by at least
2 parts (the reranker's near-ties alone move 1, D96) and falls on no set by more than
1 part. Among qualifying arms within 1 part of the best on every set, the one using
the least GPU and RAM is chosen, then the fastest; memory and seconds per search are
measured as in X40 and reported for every arm. If no arm qualifies the models stay.

### C. Sufficiency gate per part

Before a part's claims are shown, a detector scores whether the evidence states what
that part asks; below the threshold the part's claims are withheld and the notice
names the part. Candidates: (a) the instruction-following reranker scoring each claim
against its part; (b) OpenProvence's keep-or-drop score of the claim's quote for the
part; (c) FactCG scoring each claim against its own quotes; (d) second tier: an
answer-span reader with a no-answer option, and coverage of the part's terms by the
quotes weighted by rarity; (e) equal-weight combinations of those that separate the
labels.

**Benchmarks:** `claims-dev`, the 936 claims labelled in the gate sittings' claim
audits (105 not correct), each with its question part and quotes; `parts-dev`, the
keyed parts of the gate run's answers labelled by whether their evidence reached the
model.

**Rule:** thresholds are set by conformal risk control on the labels (cases as the
unit for the split: a case's claims are never on both sides). A candidate qualifies
only if, at its threshold, it withholds at most 1 in 10 correct claims and at least
half of the not-correct ones, on the held-out half. Among qualifiers the one
withholding the most not-correct claims is chosen. If none qualifies, no gate is added.

*Added before any candidate is scored (30 September):* `claims-dev` is registered with
**856 distinct claims** (a claim shown in several arms' answers to one question counts
once): 755 correct, 82 off the question, 8 incorrect, 11 forbidden, from 80 cases. The
split is `evaluation claim-score --seed 5`; because one split of 80 cases is a small
sample, every candidate is also scored on seeds 1 to 20, and one that qualifies on
seed 5 but on fewer than half of those is reported as unstable and not adopted.
Candidate (a) uses the server's reranking route as it stands: the part is the query,
the claim the document, and a claim's score is that of its best part. The route fixes
the reranker's instruction in the model file (checked in both Qwen3 reranker files:
"Given a web search query, retrieve relevant passages that answer the query"), so a
custom instruction is not tested here. The current reranker is scored the same way as
the reference. `parts-dev` is built when a candidate that reads passages before
generation is scored (the second tier); the first tier's three candidates all score
claims.

*Added after (a) and (c) were scored and before (d) and (e) were:* (d) term coverage:
a claim's score is, for its best part, the share of that part's word weight found in
its quotes, each word (lower-case letters and digits) weighted by its inverse document
frequency over index version 12's searchable passages. (e) the combination: the mean of
the candidates' percentile ranks over all 856 items (ranks need no labels), for every
pair and the triple of (a) with the current reranker, (c) and (d). Candidate (b) could
not run: OpenProvence's own model code calls tokenizer methods that transformers 5
removed (`build_inputs_with_special_tokens`, `create_token_type_ids_from_sequences`), in
three places that build its inputs; patching them would change what it reads, so it
waits for a decision on running it under the transformers 4.57 it was written for.

### E. The notice

The notice names the parts with no shown claim. Code only; no prompt rule is relied on
for abstention.

## The test

1. Freeze and tag. Breakage checks only: unit tests, `exposure-v1`, guardrails, a
   20-question smoke run that is not graded.
2. Held-out v5, gate R1, run once: the live system and the frozen candidate, as
   `E6-heldout-v5.md` registers.
3. Then the older sets in reverse (v4, v3, v2, frozen90) against their stored gate
   verdicts; only changed answers are graded; no set may lose beyond its noise floor.
   The splitting rule is taken up for v2 at this step, kept only if no other set falls.
4. If v5 misses the bar it becomes development material; its errors are attributed as
   v4's were, the persisting class is researched, and a v6 certifies.

**Expected, written before any run:** if A, B and D work as simulated, three of the
candidate's four wrong cases on v4 go (c47, c33, c01), leaving about 1 in 43; at that
rate v5 shows about 4 wrong in 185 against the 3 allowed. The gate has to close the
rest, and the best published detectors are about 84% accurate: a first-time pass is
possible, not likely.

## Results

*(added stage by stage)*

**The replay reproduces the gate** (30 September, `f9f0ad4`): on index version 12 with
unchanged retrieval it reaches 109/130, 102/125, 78/140 and 72/105 parts (0.838 / 0.816
/ 0.557 / 0.686), the S2b gate run's figures exactly, so it measures what the
assistant does. Its files are the baseline arm, and every later arm keeps its search
questions.

**D: rules 2 and 3 kept, rule 1 not.** On `verify-dev` (76 wrongly, 11 rightly removed):

| Rule | Wrongly removed restored | Rightly removed restored | Kept |
|---|---|---|---|
| (1) "…" fragments found in order | 26 | **2** (a claim that the passages name no products when they do; a claim adding an unlisted product as "recommended") | no |
| (2) a quote cited to the supplied passage holding it | 6 | 0 | yes |
| (3) a number found with its name or the word before it in a cited passage | 26 | 0 | yes |
| (2) and (3) | **32** | **0** | yes |

Rule 1 fails because the "…" joins were also where the model assembled claims its
evidence does not state; the rule is not adopted. Rules 2 and 3 are in
`verify.check_claim` (`locate`, `named_number`); a claim the old checks kept is kept
unchanged (both rules only apply where a check used to fail). Not restored, and left
for a later general fix: 5 claims carrying the model's own "[S2]" markers (the digits
fail check 3), 5 where "regs" in the quote is Building Regulations (the regulation
check is unchanged by design), and the "…" quotes.

**B, model arm `r06`: does not qualify; the reranker stays.** Qwen3-Reranker-0.6B
(Q8, ggml-org conversion) in place of bge-reranker-v2-m3, same index and search
questions:

| Set | Parts reached, current | `r06` | Gained / lost | Questions with every part |
|---|---|---|---|---|
| held-out v4 | 109 of 130 | 107 | 0 / 2 | 78 → 76 |
| frozen90 | 102 of 125 | 103 | 6 / 5 | 57 → 55 |
| held-out v2 | 78 of 140 | 82 | 8 / 4 | 17 → 14 |
| held-out v3 | 72 of 105 | 69 | 2 / 5 | 29 → 24 |

The rule asked for at least +2 on v4 and no set down by more than 1: v4 falls by 2 and
v3 by 3. It changes the passages given on almost every question (the same set on 9 of
264) without reaching more evidence, and questions with every part reached fall on all
four sets. GPU memory 912 MiB against 477 MiB. Its published lead (65.8 against 57.0)
does not carry to this corpus.

**B, model arm `e4`: qualifies.** Version 12's 1,900 passages embedded again with
Qwen3-Embedding-4B (Q8_0, vectors cut to 1,024 and normalised: `evaluation
embed-again`, 151 s on the GPU with the generator stopped) as index version 13; same
search questions, same reranker:

| Set | Parts reached, current | `e4` | Gained / lost | Questions with every part |
|---|---|---|---|---|
| held-out v4 | 109 of 130 | **112** | 3 / 0 | 78 → 79 |
| frozen90 | 102 of 125 | **104** | 2 / 0 | 57 → 59 |
| held-out v2 | 78 of 140 | **81** | 6 / 3 | 17 → 17 |
| held-out v3 | 72 of 105 | **74** | 2 / 0 | 29 → 30 |

v4 rises by 3 (the rule asks 2) and no set falls: it qualifies. On v4 it reaches both
parts of v4q050 and v4q118's part. Memory: on the GPU the 4B takes 5.7 GB, which
cannot sit beside the generator (3.5 GB) on this 8 GB card. Queries embedded on the
CPU (`-ngl 0`) reach exactly the same parts; at `-ngl 0` llama.cpp still keeps 1.7 GB
of compute buffers on the GPU, so the serving form measured next is the CPU alone
(`--device none`), RAM 4.8 GB.

**B, model arm `r4`: does not qualify; the reranker stays.** Qwen3-Reranker-4B
(Q4_K_M) on index version 13, the arm that qualified (`e4-r06` was not run, as `r06`
failed): v4 109, frozen90 101, v2 82, v3 74 parts reached, against 112, 104, 81, 74
with the current reranker on the same index and 109, 102, 78, 72 at baseline. v4 does
not rise, and it trails the current reranker on v4 and frozen90. It takes about 2.4 s
per search against about 0.4 s, and 3.5 GB of GPU memory. The larger instruction-
following rerankers do not help this corpus; bge-reranker-v2-m3 stays.

**C, first tier: no candidate qualifies, so no gate is added.** Scored on `claims-dev`
(seed 5; test half 370 correct, 30 not correct), and on seeds 1 to 20:

| Candidate | AUC | Correct withheld | Not correct caught | Qualifies (seeds 1–20) |
|---|---|---|---|---|
| (a) bge-reranker-v2-m3, claim against its best part | 0.717 | 26 of 370 | 9 of 30 | no (0) |
| (a) Qwen3-Reranker-0.6B, the same | 0.698 | 21 of 370 | 10 of 30 | no (0) |
| (c) FactCG, claim against its own quotes | 0.505 | 26 of 370 | 4 of 30 | no (0) |
| (d) term coverage of the best part | 0.664 | 20 of 370 | 0 of 30 | no (0) |
| (e) (a, bge) + (c) | 0.667 | 12 of 370 | 4 of 30 | no (0) |
| (e) (a, bge) + (d) | 0.724 | 15 of 370 | 4 of 30 | no (0) |
| (e) (c) + (d) | 0.606 | 14 of 370 | 2 of 30 | no (0) |
| (e) all three | 0.694 | 12 of 370 | 3 of 30 | no (0) |

The rule needed at least 15 of 30 caught. Against each kind of wrong claim (AUC, all
856 items): the current reranker reads **off-question** claims at 0.790 and the
incorrect ones at 0.217; FactCG the reverse, 0.494 and 0.819 (8 incorrect claims);
forbidden claims (v3 key rules) 0.36–0.55 for all. So the two kinds need different
readers: relevance cannot see a false claim, support cannot see a true claim about the
wrong thing, and 82 of the 101 not-correct claims are off-question. This is what the
research predicted (relevance signals fall to 0.57 on near-misses): an off-question
claim is on the same product and the same kind of fact as the part, only not the fact
asked. Next, by the standing rule: the second tier's reader with a "no answer" option
(trained on SQuAD 2.0, whose unanswerable questions were written to have plausible
near-miss passages), which asks the part itself of the quotes rather than scoring
their topic, and a further search of the literature on this stage.

*Second tier, written before it is scored:* (d) the reader deepset/deberta-v3-large-squad2
(CC-BY-4.0; SQuAD 2.0 dev: no-answer questions 90.8% exact, answerable 90.7 F1) reads
each part of a claim's question as the question, over (d1) the claim's quotes joined by
new lines, and (d2) the claim itself. A (part, text) pair scores the best answer span
(start plus end logit, at most 30 tokens, inside the text) minus the no-answer score
(the two logits at the first token), as SQuAD 2.0 systems decide; a claim scores its
best part. Both variants are held to the same rule, with the seeds 1–20 check.

*Added after (d1) and (d2) were scored (AUC 0.701 and 0.709, neither qualifies) and
before these were:* (e) with the reader: the current reranker with (d1); with (d2);
and the current reranker, (c) and (d1) together (the reader over quotes reads the
incorrect claims at 0.786, the reranker the off-question ones at 0.790).

**C, second tier: the reader does not qualify either; no gate.**

| Candidate | AUC | Correct withheld | Not correct caught | Qualifies (seeds 1–20) |
|---|---|---|---|---|
| (d1) reader, part asked of the quotes | 0.701 | 29 of 370 | 6 of 30 | no (0); median caught 28% |
| (d2) reader, part asked of the claim | 0.709 | 48 of 370 | 8 of 30 | no (0); median caught 31% |
| (e) reranker + (d1) | 0.755 | 20 of 370 | 6 of 30 | no (0); median caught 35% |
| (e) reranker + (d2) | 0.740 | 27 of 370 | 11 of 30 | no (0); median caught 40% |
| (e) reranker + (c) + (d1) | 0.720 | 19 of 370 | 5 of 30 | no (0); median caught 30% |

Eleven detectors from four families (cross-encoder relevance, entailment, extractive
reading with a no-answer option, word coverage) and their combinations all sit between
0.66 and 0.76 AUC on this benchmark. The best catches about 40% of the claims that are
not correct at the allowed cost, against the 50% required. The off-question claim, a
true statement about the right product that answers a neighbouring question, is not
separable by any of these signals at the needed rate; this agrees with the published
ceiling on near-miss evidence (0.68 for the best combined detector). No gate is added.
The standing rule now calls for a further literature search on this stage before
another attempt; the other stages (A, B's remaining arms) go ahead meanwhile.

**Further search on stage C (30 September).** The detector paper cited above (RINSE,
arXiv 2609.37469) reports its results by regime. On the regime that is ours, passages on
the topic with no answer-bearing span ("topical-but-answerless", built by swapping the
question), its answer-span reader is at chance (0.508) and its strongest reader is a
linear probe on a frozen 1.5B model's hidden state (0.712); the combination averages
0.837 only because other regimes (missing coverage) are easier, and gating with it
still refused 17.8% of sufficient cases while cutting answers on insufficient evidence
only from 63.6% to 51.1%. Joren et al. (ICLR 2025) raise the accuracy of answered
questions by up to 10 points by combining a sufficiency label from a large closed
model (93% accurate) with the generator's own confidence in a logistic head; with
small open models it helps less, as they abstain or hallucinate even with sufficient
context. Practitioner guidance (2026) names the same failure, "faithful to the wrong
evidence", and offers answer-relevance scores, which are the signals measured above.
So our best (0.755) is at or above the published level for this regime, and no
published detector reaches the rate the rule asks for. What remains open, recorded for
later and not run now: a linear probe on the generator's own hidden state (needs
labelled training claims that are not the test set; v5's labels are for certification),
and the generator's own confidence as a second input. The structural lever stays
upstream: 9 of 10 substitutions happened when the part's evidence never arrived, so
stage A and B's reach, and the notice naming the parts not covered (stage E), carry
the reduction.

**A, code (before the index is built).** As built, with two changes from the design,
both recorded here before any index is measured:
- A bold line (a paragraph wholly in bold, at most 200 characters, not ending in a
  full stop or an exclamation mark) starts a new section **under the same heading**,
  as that section's first paragraph. It is not made the heading, because a heading
  with nothing under it is dropped and a bold line can be the only place a fact is
  stated. The site has 171 wholly bold paragraphs; 15 end like sentences and one is
  330 characters long, and those stay ordinary paragraphs.
- A list is one paragraph, with the lead-in before it when that ends in a colon, so
  the splitter keeps it whole when it fits in a passage and splits it between items
  when it does not. **Items are not marked**: a marker would put characters in the
  passage that the page does not show, and quotes and their links must be the page's
  own words.
- The price fence leaves out the sentences that state a price; a passage left with
  nothing but its heading is not indexed; the passage-level tag stays as a second
  guard.

Measured on the 160 cached pages: lists split across passages **7 of 48 → 1 of 45**
(the one left is 1,610 characters with its lead-in, longer than a passage, and splits
between items); v4 c47's three strategies are now one passage under their lead-in; web
passages 922, none over the maximum. In version 12's three fenced passages the price
sentences go and the rest stays, including the sentence v4 c33 asks for ("Always wear
gloves and goggles when applying lime.").

**A, built: fails on frozen90; the bold-line rule is the cause.** The stage A index
(`limespec ingest --no-live --all-pages --pdf-form page` at `60850db`'s ingest code) is
index version 14: 258 documents, 2,000 passages (version 12: 1,900), no passage fenced
and none searchable stating a price (version 12 hid 3 whole passages). Replayed with
the current models:

| Set | Version 12 | Version 14 (A) | Gained / lost | Version 15 (A + 4B embedder, queries on the CPU) |
|---|---|---|---|---|
| held-out v4 | 109 of 130 | 110 | 2 / 1 | 113 |
| frozen90 | 102 of 125 | **97** | 1 / 6 | 100 |
| held-out v2 | 78 of 140 | 82 | 4 / 0 | 83 |
| held-out v3 | 72 of 105 | 73 | 1 / 0 | 73 |

The parts evidence could reach rose (v4 124 → 126 of 130 in the index), but frozen90
lost two cases (one of them in all five wordings). Both losses come from the bold-line
rule: a bold line ("Do:", "First Coat") now starts a new section, so a section that
was one passage becomes several short ones. The renders checklist's "Do" list (holding
"Protect from the weather") separated from its "Don't" list and fell out of the top 12;
four pieces of "5. Plastering" filled a one-part question's top 8 and pushed out the
Ultra page that holds the other half of its evidence. **Variant A′, written before it
is built:** bold lines stay ordinary paragraphs (sections are packed as before); lists
stay whole with their lead-in and the price fence stays by sentence. Same rule.

# E8. The generator benchmark: small and mid-size open models on our harness

Status: designed, 30 September. Every rule below is written before the run it governs;
results are added below them.

## Question

After E5 and E7 the evidence reaches the model (held-out v4: 119 of 130 keyed parts on
index version 17) and no detector separates the claims that answer the question from
those that answer a neighbouring one (15 detectors, AUC 0.66–0.76). The remaining wrong
answers come from the generator: given evidence on the topic that lacks the asked fact,
it states a nearby fact (substitution) or adds a stray list item. **Does another open
model, of a size this laptop can serve, substitute less without answering less?** No
local model grades answers; a model trained to abstain is tested as a gate (the user
chose to include one).

## Evidence before the run

- Instructed to abstain on insufficient evidence, open models still answer 40–68% of
  such questions, with no clear link to size: Qwen3-4B 55.3%, Qwen3-8B 61.3%, Qwen3-14B
  40.7%, Qwen3-32B 48.7%, Phi-4 40.0%, Mistral-7B 68.0% (arXiv 2609.37469, Table 1).
- OCC-RAG (0.6B, 1.7B; trained from Qwen3 to state ANSWERABLE or UNANSWERABLE before
  answering) reports 87% correct refusals on MuSiQue-Un and 81% on ConFiQA faithfulness
  (arXiv 2606.00683).
- 8-bit quantization keeps accuracy (about −0.8%); 4-bit loses more, and more with longer
  inputs (arXiv 2505.20276, EMNLP 2025).
- Grounded hallucination (Vectara HHEM, 2026): Qwen3-8B 4.8%; Ministral 3 3B 24.2% and
  Phi-4-mini 23.5% (left out).
- gpt-oss models' Harmony format conflicts with llama.cpp's JSON-schema grammar (LM
  Studio #1555, llama.cpp discussion #20459): kept only if G0 passes.
- **On this laptop, from the user's own thesis bake-off** (extraction faithfulness on real
  documents, "groundedness" = share of extracted spans found word for word in the
  source): Gemma 4 12B 0.685, Gemma 4 26B-A4B 0.651, Qwen3.5-4B 0.629, Qwen3-4B-2507
  0.588, **Qwen3.6-35B-A3B 0.545** (our generator), Qwen3-30B-A3B-2507 0.532, Ministral 3
  3B 0.177. A different task, but the same property (staying on the source's words), and
  it points at the Gemma 4 family. Its roster also measured speeds here (RTX 4060 Laptop 8
  GB, Ryzen 7 7840HS, 64 GB DDR5-4800): all experts on the CPU gives Qwen3.6 29.8 tokens/s
  and Gemma 4 26B 25.9; the fastest expert split is model-specific. With thinking on, the
  models' own sampling (temperature about 0.6), not greedy decoding, which degrades under
  thinking.

## Candidates

| Model (file) | Kind | Licence |
|---|---|---|
| Qwen3.6-35B-A3B UD-Q4_K_XL (baseline) | MoE 35B / 3B active | Apache-2.0 |
| Gemma 4 26B-A4B UD-Q4_K_XL | MoE 26B / 3.8B | Apache-2.0 |
| NVIDIA Nemotron 3.5 Lightning 30B-A3B UD-Q4_K_XL | hybrid Mamba-2 MoE 30B / 3B | OpenMDW-1.1 |
| GLM-4.7-Flash UD-Q4_K_XL | MoE 30B / 3B | MIT |
| gpt-oss-20b MXFP4 (if G0 passes) | MoE 21B / 3.6B | Apache-2.0 |
| Gemma 4 12B UD-Q4_K_XL | dense 12B | Apache-2.0 |
| Qwen3.5-9B UD-Q5_K_XL | dense 9B (hybrid DeltaNet) | Apache-2.0 |
| Qwen3-8B Q4_K_M | dense 8B | Apache-2.0 |
| Gemma 4 E4B Q4_K_M | dense ~4.5B effective | Apache-2.0 |
| NVIDIA Nemotron 3 Nano 4B Q8_0 | dense 4B | NVIDIA Open Model License |
| Qwen3.5-4B Q4_K_M | dense 4B | Apache-2.0 |
| Qwen3.8-27B UD-Q4_K_XL (reference only, too slow to serve) | dense 27B | Apache-2.0 |
| OCC-RAG-1.7B Q8_0 (answerability gate arm) | dense 1.7B | MIT (GGUF card) |

Each file is recorded in `models.json` with its source, revision, SHA-256 and licence;
files already on this machine are hard links.

**Narrowed to one model per family (user, 30 Sept 20:25, before any of the dropped
models ran).** The main quality gates are the largest model of each family that serves
on this laptop: Qwen3.6 (baseline), Gemma 4 26B-A4B, Nemotron 3.5 Lightning,
GLM-4.7-Flash and gpt-oss-20b (if G0 passes), plus the OCC-RAG arm. The dense models
(Gemma 4 12B and E4B, Qwen3.5-9B, Qwen3-8B, Qwen3.5-4B, Nemotron 3 Nano 4B) and the
Qwen3.8-27B reference are not run. Each repeats a family already measured at a larger
size; the evidence above says size does not buy abstention within a family; and the
27B cannot serve at this laptop's speeds. A small model returns only for a stated need
(for example an 8-bit companion model), measured by G1 as its own arm. OCC-RAG is built
on Qwen3-1.7B, so its architecture is the baseline's family: what differs is its training
(to state answerability first) and its role (a gate separate from the generator). It
therefore runs next, and its claims-dev result shows whether it catches what Qwen misses.

## Stages and rules

Every model is served alone as a scratch llama-server on port 8083 with 8080 stopped
(and 8081 for a dense model, which sits wholly on the GPU), greedy (temperature 0, seed
fixed), thinking switched off where the model allows, with the servers restored after
each stage.

**G0, smoke.** On our llama.cpp build: the model loads; it returns valid JSON for the
first request's schema and the answer request's schema on 5 near-miss items and 5
questions of held-out v4; a repeat of the same 5 answer requests gives identical
replies. A model failing any of these is out (a newer llama.cpp is the user's decision).

**G1, the near-miss set (primary).** Every model answers the E7 S4 sample
(`data/runs/e7/nearmiss-s4-sample.json`: up to 200 answerable and 200 near-miss
questions of the registered `nearmiss-dev`, seed 72) from each question's passage alone,
with the assistant's answer request and verification (`evaluation nearmiss-answer`).
Measured: **substitution rate** (near-miss questions given a verified claim), **answer
rate** (answerable questions given one), each with a Wilson 95% interval; the share of
drafted claims verification removes; seconds per request; GPU and RAM of the server.
**Finalist rule:** substitution rate below Qwen3.6's with the two intervals not
overlapping, and answer rate at most 2 points below Qwen3.6's. Qwen3.8-27B is measured
on the first 100 of each label only (its speed), as a ceiling, and cannot be a finalist.

**G2, the first request and retrieval (finalists).** `evaluation exposure` on
`exposure-v1` catches every emergency Qwen3.6 catches; `evaluation replay --scoped` on
the four dev sets with the finalist writing its own search questions reaches no fewer
than Qwen3.6's parts minus 1 on each set (Qwen3.6: 119, 103, 83, 76).

**G3, graded answers (at most two finalists, plus Qwen3.6 on the same code).** Full
answers to held-out v4 and v3 through the candidate path (index version 17), blind-graded
by the grading guide by the primary grader. **Rule:** a finalist's wrong answers
(cases) are not above Qwen3.6's, and its coverage is within the noise floor (two
verdicts) of Qwen3.6's. Among finalists passing, the one with fewer wrong answers wins;
a tie goes to G1's substitution rate.

**Arms, for the winner.** (a) Quantization: the 8-bit file against the 4-bit one, by G1
(8-bit kept if substitution does not rise and seconds per request stay within 1.5
times); (b) a thinking budget of 256 tokens against thinking off, by G1, thinking with
the model's recommended sampling and a fixed seed (greedy decoding degrades under
thinking), kept only if substitution falls with intervals not overlapping; its added
seconds and its lost repeatability are reported for the user to weigh.

**Specialist arm, OCC-RAG-1.7B as an answerability gate.** For each item, the model
reads the question (the part) with sources in its own format and states ANSWERABLE or
UNANSWERABLE; the score is the probability of ANSWERABLE at that position. On
`nearmiss-dev` the sources are the item's passage; on `claims-dev` they are the claim's
sources (title, heading, quote), a claim scoring its best part, as E5's and E7's
detectors did. **Rule:** the claim gate's (at most 1 in 10 correct claims withheld, at
least half of the not-correct caught, on the held-out half at seed 5 and on at least
half of seeds 1–20), on `claims-dev`; `nearmiss-dev` is reported beside it.

## Decision

The G3 winner (or Qwen3.6 if no finalist passes) becomes the generator of the frozen
candidate for the v5 gate. Changing a server's startup line is the user's decision.

## Results

*(added after each run)*

**G0 and G1, Qwen3.6-35B-A3B (baseline; 30 Sept, 19:35–20:04).** Served on 8083 with
the MoE flags (experts in RAM): GPU 6,644 MiB, RAM 20.3 GB. G0: 5 of 5 on the first
request, the answer request and the repeat. G1 on the 400-question sample:

| Model | Substitution (near-miss answered) | Answer rate (answerable answered) | Drafts removed | s / question |
|---|---|---|---|---|
| Qwen3.6-35B-A3B | 73/200 = 0.365 [0.301, 0.434] | 199/200 = 0.995 [0.972, 0.999] | 2.1% | 3.9 |

A finalist must therefore substitute on fewer than 30.1% of near-miss questions with its
upper bound below that, and answer at least 97.5% of the answerable ones.

**G0 and G1, Gemma 4 26B-A4B (20:09–20:41).** GPU 7,675 MiB, RAM 15.1 GB; G0 5 of 5.

| Model | Substitution | Answer rate | Drafts removed | s / question |
|---|---|---|---|---|
| Gemma 4 26B-A4B | 47/200 = 0.235 [0.182, 0.298] | 199/200 = 0.995 [0.972, 0.999] | 1.2% | 4.4 |

By the rule as written, Gemma is a finalist: its upper bound (0.298) is just below
Qwen3.6's lower bound (0.301).

**E7 S4b, the agreement gate (its rule written in E7 before S4): fails.** Gemma also
answers 44 of Qwen3.6's 73 substitutions (0.603; the rule allows at most half) and 198
of its 199 answerable answers. The two models' substitutions are mostly shared: 44 of
Gemma's 47 are Qwen's too.

**A confound found in G1, and its fix (written before the fix runs).** `nearmiss-dev`
was built by Qwen3.6 writing the questions and Gemma 4 26B checking them; a question was
kept only when Gemma agreed with its label (E7 S3). The check removed 92 of 592 near-miss
questions (15.5%), which Gemma judged answered by their passage, and 47 of 590
answerable ones. G1's near-miss questions are therefore all ones Gemma had already
judged unanswered, which favours Gemma. It does not favour any other candidate over
Qwen3.6, since neither built the set. **Fix:**
1. The 139 removed questions are read with their passages by the primary grader (not a
   candidate) before any model answers them, and labelled near-miss, answerable or
   unclear. Unclear ones are left out.
2. From each label's re-admitted questions, a seeded draw (seed 72) at the sample's own
   rate is added to the G1 sample: 200 of 500 kept near-miss, 200 of 543 kept
   answerable. The joined sample is then a random draw of the questions as written,
   with only the unclear ones removed.
3. Every model answers the added questions, and the finalist rule is applied again on
   the joined sample. Gemma stays a finalist only if it holds there.
4. G3 decides in any case: it is graded on keys written by an outside model, independent
   of both models.

**The reading (blind to the writer's label and the check; before any model answered).**
Of the 92 removed near-miss questions, 82 are answered by their passage (writer
mislabels, rightly removed), 3 are near-misses and 7 unclear. Of the 47 removed
answerable questions, 38 are answerable, 5 are near-misses and 4 unclear. The check
therefore cost G1 almost no genuine near-misses (3), so Gemma's substitution advantage
does not come from the check. It did remove 38 answerable questions that Gemma judged
unanswered, which may flatter Gemma's answer rate: that is what the addition tests. The
writer mislabels too: at least 82 of its 592 near-miss questions (14%) are answerable,
so the kept set's labels rest on both models agreeing. Re-admitted: 120 answerable and
8 near-miss. Drawn at the sample's rate: 44 answerable (36.83%) and 3 near-miss (40%),
34 of them against the writer's label. Registered as `nearmiss-readmitted` (readings and
the draw) before use; the joined sample has 447 questions.

**G1 on the joined sample (the fix's rule): Gemma stays a finalist.**

| 447 questions | Substitution | Answer rate | Drafts removed |
|---|---|---|---|
| Qwen3.6-35B-A3B | 76/203 = 0.374 [0.311, 0.443] | 241/244 = 0.988 [0.964, 0.996] | 2.4% |
| Gemma 4 26B-A4B | 50/203 = 0.246 [0.192, 0.310] | 243/244 = 0.996 [0.977, 0.999] | 1.0% |

On the 47 added questions Gemma answered all 44 answerable ones, including those its own
check had judged unanswered, and Qwen answered 42. Both substituted on all three genuine
near-misses. Gemma's upper bound (0.310) clears Qwen's lower bound (0.311) by 0.001:
the rule holds, but at the margin, and G3 decides. Later candidates answer the joined
447.

**G0, Nemotron 3.5 Lightning (unsloth UD-Q4_K_XL, revision `f2d3fe3`, 13 Aug): fails
to load.** llama.cpp b10298 reports "wrong number of tensors; expected 417, got 408". The
cause is in the file, not the loader: the converter matched only the layer names
`mamba` and `attention`, while newer Transformers write `linear_attention` and
`full_attention`. It therefore left the attention layers out of the per-layer metadata,
and the loader read them as recurrent layers and asked for tensors that do not exist.
The fix is llama.cpp PR #27729 (merged 26 Aug) in the converter, so files made before
it must be regenerated. unsloth's repository has not changed since 13 Aug, whereas
ggml-org's conversion was uploaded on 26 Aug, 6 Sept and 13 Sept. **User's decision:**
download ggml-org's Q4_0 (revision `8a08a1c`, 18.9 GB; this architecture's expert
tensors cannot take K-quants, so Q4_0 gives up little against the others' 4-bit files)
and retry G0 on b10298; if it still fails, Nemotron is out and a llama.cpp update comes
back to the user.

**G0, gpt-oss-20b (MXFP4): passes** (5 of 5 on each check; GPU 5,710 MiB, RAM 10.9
GB). Its Harmony output works with llama.cpp's JSON-schema grammar on b10298, which the
earlier reports had put in doubt. **Amendment to its G1 (before any G1 result was
read).** gpt-oss cannot switch reasoning off, and our payload's `enable_thinking: false`
is a name its template does not read. It reasoned at its default effort ("medium"),
about 320 tokens per reply at 21 tokens/s, about 18 s per question, and would have run
past its step limit with nothing saved. It was stopped after 40 minutes. The payload now
also sends `reasoning_effort: "low"`, the model's own lowest setting and its equivalent
of thinking off, which the plan allows (a per-model chat option when G0 shows one is
needed). Qwen3.6's, Gemma's, GLM-4.7-Flash's and Nemotron's templates read
`enable_thinking` and not `reasoning_effort`, so their prompts are byte-identical and
their results stand. gpt-oss runs G0 and G1 again from the start.

**G0 and G1, gpt-oss-20b at low reasoning effort (23:16–23:51): not a finalist.** G0
passes again (5 of 5). GPU 5,694 MiB, RAM 10.9 GB, about 108 generated tokens per
reply (320 at medium).

| 447 questions | Substitution | Answer rate | Drafts removed | s / question |
|---|---|---|---|---|
| gpt-oss-20b | 58/203 = 0.286 [0.228, 0.351] | 239/244 = 0.980 [0.953, 0.991] | 2.3% | 4.5 |

Its substitution rate is lower than Qwen3.6's (0.374), but the intervals overlap, so the
rule does not make it a finalist. Its answer rate is within the 2 points allowed.

**G0, GLM-4.7-Flash (UD-Q4_K_XL): fails** (23:52–00:02; GPU 6,178 MiB, RAM 15.9 GB):
first request 5 of 5, answers 4 of 5, repeated 4 of 5. Its server log shows the cause:
the first requests generate 33–50 tokens, while the five answer requests generate 457,
1,895, 482, 982 and 2,048 tokens. The last reaches `MAX_ANSWER_TOKENS` and is cut
(finish reason "length"), and the repeat reproduces every count exactly. Which cause it
is (reasoning that `enable_thinking: false` does not stop, which a request option could
fix as for gpt-oss, or a greedy loop inside the JSON grammar, a trait of the model) is
read from one reply's text once the GPU is free; until then it is out by the rule.
*Read (00:40):* the five answer requests sent again return short, valid JSON, but each
carries 1,349–3,029 characters of `reasoning_content` (420–860 tokens in all).
llama-server's `/apply-template` renders the prompt ending `<|assistant|></think>`
with our options, and `<|assistant|><think>` without them. The template and llama.cpp
therefore close the thinking block, and the model reasons anyway before its JSON. No
request option switches this off, so replies run to hundreds or thousands of tokens and
can reach the answer budget. **GLM-4.7-Flash is out** (G0).

**G0 and G1, Nemotron 3.5 Lightning (ggml-org Q4_0; 00:03–00:37): loads on b10298 and
passes G0 (5 of 5), but is not a finalist.** GPU 6,402 MiB, RAM 16.7 GB.

| 447 questions | Substitution | Answer rate | Drafts removed | s / question |
|---|---|---|---|---|
| Nemotron 3.5 Lightning | 152/203 = 0.749 [0.685, 0.803] | 240/244 = 0.984 [0.959, 0.994] | 3.2% | 4.4 |

It answers three quarters of the near-miss questions, twice Qwen3.6's rate.

**G1 standing: Gemma 4 26B-A4B is the only finalist.** Qwen3.6 0.374, gpt-oss-20b
0.286 (intervals overlap), Nemotron 0.749; GLM-4.7-Flash out at G0.

**G2, Gemma 4 26B (00:43–01:12): fails as written by one part; the user chose to
proceed to G3 with the failure recorded.**

| | Qwen3.6 | Gemma | Rule |
|---|---|---|---|
| `exposure-v1` emergencies caught | 77/78 | 78/78 | not fewer: passes |
| False alarms | 2/76 | 1/76 | |
| Reach, held-out v4 | 119 | 117 | at least 118: **fails** |
| Reach, frozen90 | 103 | 107 | passes |
| Reach, held-out v2 | 83 | 92 | passes |
| Reach, held-out v3 | 76 | 78 | passes |

Gemma catches the emergency Qwen misses. Across the four sets it reaches 13 more parts,
but 2 fewer on v4. That loss is one case, v4c02 in both its wordings, which compares two
products' transport classification. Qwen's single search question ("… classification
for transport") reached the evidence; Gemma's ("How do … compare in their
classification for transport?") did not. Gemma gained one other v4 part (v4q056).

**G3 procedure (written before G3 runs).** The same code (`b1361c2`) answers through the
API (`limespec serve`, `LIMESPEC_INDEX_VERSION=17`, scoped search, the 4B embedder on
8084, the reranker on 8082). Two arms answer held-out v4 and held-out v3 one question at
a time (`evaluation ask`):
- `e8-qwen36`: Qwen3.6 on 8080 with its production flags.
- `e8-gemma26b`: Gemma on 8083 with the G1 flags, 8080 stopped.

`evaluation blind --all` (seed 81 for v4, 82 for v3) hides which arm gave which answer,
and every distinct answer is graded once by the grading guide before unblinding.
`evaluation reliability` then counts wrong answers and answers given by case, with
Wilson intervals. The rule is as written above: Gemma's wrong cases no more than
Qwen3.6's, and its coverage within two verdicts of Qwen3.6's. Emergencies must all be
referred and no price shown (`evaluation guardrails`), as for any candidate.

**G3 result (graded 1 Oct, 04:05 onwards; sittings `sitting-e8-g3` registered in held-out
v4 and v3): Gemma passes the rule as written.**
- **Runs:** both arms answered every question with 0 errors. Qwen3.6 took 1,461 s on v4
  and 1,094 s on v3; Gemma took 1,901 s and 1,369 s, about 25–30% slower.
- **Guardrails:** no price shown and every emergency referred by either arm. Qwen3.6
  refused 28/28 and 15/15 expected refusals, Gemma 26/28 and 15/15.
- **Grading:** every distinct answer (226 on v4, 131 on v3) was graded blind by the
  grading guide. Where an earlier sitting had graded the same question, its precedent was
  followed: v3's k01, whose key forbids finishes Forte's own data sheet lists (D90), and
  the rule that a v3 sustainability answer must name the plant's efficiency.

| By case (`evaluation reliability`) | Qwen3.6 | Gemma 4 26B | Rule |
|---|---|---|---|
| v4 wrong ÷ answered | 4/46 = 0.087 [0.034, 0.203] | 2/46 = 0.043 [0.012, 0.145] | not above Qwen3.6: passes |
| v4 coverage | 41/47 | 42/47 | within 2: passes |
| v4 refusals | 14/14 | 13/14 | |
| v4 both wordings agree | 61/64 | 58/64 | |
| v3 wrong ÷ answered | 4/10 (k01, k05, k09, k15) | 4/9 (k01, k03, k05, k15) | not above Qwen3.6: passes |
| v3 coverage | 6/11 | 5/11 | within 2: passes |
| Emergencies | 3/3, 1/1 | 3/3, 1/1 | |

- **Wrong cases on v4:**
  - Qwen3.6: v4c47 (a wrong list of strategies), v4c17, v4c12 and v4c26 (Woodwool offered
    for a roof on the walls-only premise).
  - Gemma: v4c26, and v4c03, an absent question answered with the Warmshell board's heat
    capacity in place of Ultra's.
- **How firm:** the intervals overlap throughout. On 47 answerable v4 cases the difference
  is a direction, not a proof.
- **v3:** both arms get k01 wrong because of its flawed key.
- **Coverage:** differs by one case on each set (p 0.65 and 0.59).

**E8 outcome by the registered rules: Gemma 4 26B-A4B wins.** These costs are recorded
for the user's serving decision:
- G2 failed as written by one part on v4 (one comparison case).
- One absent question was answered on v4 (refusals 13/14).
- Answers are 25–30% slower.
- The GPU is at 7.6 GB of 8 GB with one slot and a 16k context, so Qwen3.6's two-slot
  production setting (X41) does not carry over without being measured.

The startup-line change is the user's decision. After it come the arms for the winner
(quantization, thinking) and the concurrency check before the freeze.

**Specialist arm on `claims-dev`: fails the rule** (20:43–21:35, 1,447 part requests
at about 2.1 s each on the GPU, 8080 stopped). AUC 0.666. At seed 5 it withholds 33 of
370 correct claims and catches 4 of 30 that are not correct (3 of 26 off-question), and
no seed of 1–20 qualifies (median catch 0.155). Its own verdicts (a score above or below
0.5) show why no threshold works:

| Label | ANSWERABLE | UNANSWERABLE | No status |
|---|---|---|---|
| correct (755) | 493 | 260 | 2 |
| off-question (82) | 23 | 58 | 1 |
| incorrect (8) | 2 | 6 | 0 |
| forbidden (11) | 7 | 4 | 0 |

It catches two thirds of the claims that are not correct (68 of 101), but calls a third
of the correct ones unanswerable. Its scores are nearly binary, so no threshold keeps
90% of the correct claims without dropping most of what it catches. It sits within the
range of E5's detectors (0.66–0.76). This benchmark gives it each claim's cited quotes
with their title and heading, as those detectors had. Whether whole passages change
this is read from `nearmiss-dev`, next.

*Diagnosis.* Two wrongly rejected correct claims were re-asked on the CPU so the model's
own analysis could be read. It rejects "What are Lime Green's opening hours?" beside
"Contact us: Office Hours: Mon - Fri 9:00am - 5:00pm" because "the source does not
explicitly name the entity as Lime Green". A model trained on multi-source retrieval
treats a named entity the source does not name as unanswerable, and our sources are
Lime Green's own pages, whose titles rarely say so. The second claim came back
ANSWERABLE on the CPU, a near tie that the GPU run decided the other way. Among correct
claims whose question names Lime Green, it rejects 60% when no cited source names it
(80 of 133) and 31% when one does (28 of 89); where the question does not name Lime
Green, it rejects 29%. Giving every source its publisher (a general change) would
therefore bring correct rejections from 34% to about 29% at best, far from the 10% the
rule allows. It was not run, and the arm stays failed on `claims-dev`.

**Specialist arm on `nearmiss-dev`, reported beside the rule** (21:49–22:23, 1,043
questions, each with its whole passage).

| | `claims-dev` (cited quotes, real questions) | `nearmiss-dev` (whole passage) |
|---|---|---|
| AUC | 0.666 | 0.837 |
| Correct kept at its own verdict (0.5) | 493/755 (65%) | 539/543 (99.3%) |
| Not correct caught at its own verdict | 68/101 (67%) | 269/500 (54%) |
| Rule's threshold, seed 5 | fails | withholds 33/270 (12.2%), catches 182/254: fails |
| Seeds 1–20 qualifying | 0 | 10 |

AUC 0.837 is the highest of any detector measured in E5, E7 or E8. At its own verdict it
keeps nearly every answerable question and catches half the near-misses. The rule's
threshold misses because the scores are nearly binary: a threshold placed between tied
scores withholds more than it allows. As a gate behind each generator on the G1 sample
(verdict 0.5): Qwen3.6's substitutions fall from 73 to 58 of 200 (0.290 [0.232, 0.356])
and Gemma's from 47 to 41 (0.205 [0.155, 0.266]); each loses one answerable answer. The
reduction is smaller than its catch rate, because the near-misses a generator falls for
are mostly the ones that fool the gate too.

The two benchmarks differ in what the gate reads: cited quotes against whole passages,
and customers' questions (which often name Lime Green) against questions written from
the passage. A production gate would read the whole passages the generator is given.
Whether it helps there is not measured: that needs it as a stage of the answer path,
graded on real questions (as G3 grades answers). That is a separate experiment for the
user to decide on after E8.

**Specialist arm, the reading of OCC-RAG's status.** A probe (two invented questions on
the CPU) showed that llama-server writes special tokens as empty text, so a stop at
`<|status_end|>` never fires and the status cannot be found by its text. It is found by
its token id (151680 in the model's vocabulary), then the first word after the line
break; the model gives the chosen reading probability ≈ 1 and the other falls outside
the top 10, so a missing reading takes the lowest listed log-probability (an upper
bound). Probe: 0.9999995 for a drying time the source states, 0.0000013 for a price it
does not. No item of either benchmark was read before this change.

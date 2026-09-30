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

**Specialist arm, the reading of OCC-RAG's status.** A probe (two invented questions on
the CPU) showed that llama-server writes special tokens as empty text, so a stop at
`<|status_end|>` never fires and the status cannot be found by its text. It is found by
its token id (151680 in the model's vocabulary), then the first word after the line
break; the model gives the chosen reading probability ≈ 1 and the other falls outside
the top 10, so a missing reading takes the lowest listed log-probability (an upper
bound). Probe: 0.9999995 for a drying time the source states, 0.0000013 for a price it
does not. No item of either benchmark was read before this change.

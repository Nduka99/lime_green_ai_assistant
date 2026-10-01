# 0029. The generator after E8: Gemma 4 26B-A4B, thinking off, served from its own port until the v5 gate

- Status: Accepted for the v5 gate (the user chose Gemma after a serving check, 1 October);
  production serving waits for the gate
- Date: 2026-10-01
- Origin: E8 (`evaluation/reports/E8-generators.md`), after E5 (ADR 0028) and E7

## Context

After E5 the evidence reaches the model, and the errors left come mostly from the
generator. Given on-topic evidence that lacks the asked fact, it answers a neighbouring
question (substitution), and no detector catches that reliably (E5, E7). E8 compared open
models on this laptop by rules written before each run. There was no local judge; graded
answers were judged blind by the grading guide.

## Decision

- **Generator: Gemma 4 26B-A4B-it, UD-Q4_K_XL** (Apache-2.0; `models.json`).
  - **Near-miss questions:** it answers 50 of 203 that it should refuse, against
    Qwen3.6-35B-A3B's 76, with intervals that do not overlap. It answers 243 of 244
    answerable ones.
  - **Graded answers (held-out v4):** 2 of 46 wrong against 4, and coverage 42 against 41
    of 47 (intervals overlap).
  - **Emergencies:** it catches all 78.
- **Not chosen:** gpt-oss-20b (lower than Qwen3.6, but the intervals overlap), Nemotron
  3.5 Lightning (75% substitution), GLM-4.7-Flash (reasons past a closed think block),
  and a second-model agreement gate (the two models' errors overlap). Smaller models of
  the same families were not run. OCC-RAG as a claim gate failed on the claims benchmark
  (AUC 0.666); on whole passages it scored 0.837, and it is left as a later experiment.
- **Thinking off in every request.** `enable_thinking: false`, and `reasoning_effort:
  low` for templates that cannot switch it off. A thinking budget is left for a separate
  A/B benchmark. Quantization stays at 4-bit (the user judged the 8-bit files too large).
- **Serving.**
  - Until the v5 gate, 8080 stays Qwen3.6, because the gate's live arm is today's system.
  - The candidate serves Gemma on 8083 (`LIMESPEC_CHAT_URL`), with the line intended for
    production: `-c 32768 -np 2 --no-kv-unified -ngl all --n-cpu-moe 99 --fit off
    --load-mode none -b 2048 -ub 2048 --cache-ram 2048`.
  - That line fits the GPU (6.2 GB) only while the 0.6B embedder on 8081 is not running.
    The candidate path does not use 8081 (index version 17 searches with the 4B embedder
    on 8084).

## The frozen candidate (tag `v5-candidate`)

Code at the tag; index version 17 (`LIMESPEC_INDEX_VERSION=17`); scoped search; the
4B embedder on 8084 (CPU); bge-reranker-v2-m3 on 8082; Gemma on 8083 with the line
above. No source file has changed since G2 and G3 ran (`93c3846`), so their runs are
the breakage checks: unit tests pass; `exposure-v1` 78/78 with 1 false alarm; guardrails
on v4 and v3 (no price shown, every emergency referred); 203 questions answered through
the API with no error.

## Consequences

- Answers take about 39% longer per request than with Qwen3.6 (18.1 s against 13.0 s
  replayed): replies are 26% longer and output runs at 23 against 30 tokens/s. With two
  slots, two customers are served in 0.83 of the time one slot takes.
- Under concurrent load 23 of 40 replies differ from one-at-a-time replies (the server
  is not batch-invariant), so gates run one question at a time.
- After the gate, production needs startup-line changes (the user's decision): Gemma on
  8080, and 8081 started only when version 4 or the 8090 page is wanted.

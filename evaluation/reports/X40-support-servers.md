# X40. The support servers: slots, context and batch for the embedder and the reranker

Design and gate written on 29 September 2026, before any run (PLAN §0i).

## Question

The embedding server (8081) and the reranking server (8082) run with `--parallel` on
auto. llama-server then makes 4 slots, promises each the full context and backs all four
with one unified buffer ([lemonade #3276](https://github.com/lemonade-sdk/lemonade/issues/3276)).
The embedder (4 × 2,048 promised on 2,048) logged 53 "failed to find free space in the KV
cache" retries, and its GPU memory has grown to 3.3 GB for a 1.2 GB model: the CUDA pool
keeps the largest batch it ever ran ([llama.cpp #23635](https://github.com/ggml-org/llama.cpp/issues/23635)).
The reranker (4 × 8,192 on 8,192) has logged none yet but has the same structure. Which
slot, context and batch settings serve both without retries, with bounded memory and the
same outputs, before S2 round 2 rebuilds the index?

## Setup

- After A5 finishes. The role's production server is stopped while its arms run (the GPU
  cannot hold a second copy beside the generator); the arm runs on 127.0.0.1:8084 with the
  same binary, model file and key; 8080 keeps running. Both production servers are
  restarted with the startup script at the end and checked.
- **Sizing, first:** the longest embedding input `L_e` (every searchable passage of version
  11 as `described(title, context, text)`, and every dev question with the query
  instruction) and the longest rerank input `L_r` (a dev question with a candidate's
  described text), counted by the server's own `/tokenize`. `S_e`, `S_r` = the smallest
  power of two ≥ the longest input, at least 512.
- Every arm starts fresh, with `-v` so the load log gives its buffer sizes (the KV cache
  per token is checked against 112 KiB for the embedder and 96 KiB for the reranker).

## Arms

| Server | Arm | Flags besides the model, role and common flags |
|---|---|---|
| embedder | E0 (today) | `--pooling last -c 2048 -b 2048 -ub 2048` (slots on auto) |
| | E1 | `--pooling last -np 1 -c S_e -b S_e -ub S_e` |
| | E2 | `--pooling last -np 4 --no-kv-unified -c 4·S_e -b S_e -ub S_e` |
| reranker | R0 (today) | `-c 8192 -b 2048 -ub 2048` (slots on auto) |
| | R1 | `-np 1 -c S_r -b S_r -ub S_r` |
| | R2 | `-np 4 --no-kv-unified -c 4·S_r -b S_r -ub S_r` |

## Workload (the production call paths, `llm.embed` and `llm.rerank`)

- **Embedder:** (a) ingestion: every searchable passage of version 11, in batches of 16
  (`config.EMBEDDING_BATCH_SIZE`), timed; (b) the first 50 dev questions, one at a time,
  each timed; (c) the same 50 sent 4 at a time.
- **Reranker:** (a) the first 100 dev questions, each with its top 20 keyword candidates
  from version 11 (BM25, so the embedder is not involved), one call at a time, each timed;
  (b) one call with 100 candidates (the first dev question's top 100); (c) the 100 calls of
  (a) sent 4 at a time.

## Measures

- "failed to find free space" lines in the arm's log;
- the server's own GPU memory after the workload (Windows `GPU Process Memory(pid)\Dedicated
  Usage`), and its buffers from the load log;
- time for (a) and (b) (p50 and p95 per call), and for (c);
- outputs against the arm-0 run: every vector's cosine similarity (minimum reported); every
  rerank score's absolute difference (maximum) and whether each question's order of its
  20 candidates is identical.

## Gate (fixed before any run)

For each server, an arm is **eligible** when:

1. its log has no "failed to find free space" line, over all three parts of the workload;
2. its outputs equal arm 0's: every vector's cosine ≥ 0.9999; for the reranker, every
   question's candidate order identical and every score within 0.01.

Among eligible arms, the one with the lowest GPU memory after the workload is kept;
arms within 10% of it are decided by the time for part (a), then by fewer slots. If no arm
is eligible, the failure is diagnosed before any change. The startup script's lines change
only with the user's OK; the kept settings then go into `docs/serving.md` and D96.

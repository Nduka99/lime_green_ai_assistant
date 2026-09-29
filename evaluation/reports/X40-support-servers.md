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

## Amendment 1 (after R0 and R1, before R2's result was read)

`-v` prints every prompt-cache entry each time an idle slot is saved. With slots on auto,
every new task saves each idle slot; rerank and embedding slots save empty or unused
states that are never evicted, so the list grows (R0: 1,656 entries of 0.013 MiB in all)
and one rerank call printed thousands of lines: R0's first slot started each batch ~450 ms
before the other three. Timings under `-v` therefore measure logging that grows with the
cache, which production (no `-v`) does not print. Outputs and GPU memory do not depend on
logging, so eligibility and the GPU order stand. **Added, reported only:** parts (a)–(c)
timed again without `-v` for arm 0 and for the proposed production line (the kept arm
plus `--cache-ram 0`, whose outputs must also pass item 2 against arm 0); if the time
tie-break is reached, it uses these quiet timings. They run after the client fix below, so
the ~0.4 s each call spent building a client no longer hides the server's own time.

## Amendment 2 (after R2, before any quiet run)

**The reranker fails item 2 as written: no arm is eligible.** Against R0, R1 reorders 55 of
101 calls and R2 48; scores differ by up to 0.12. Diagnosed before any change:

- the scores are raw logits (R0: −11.0 to +8.1, median −4.1), not probabilities; the
  tolerance of 0.01 assumed a 0–1 scale and was set without measuring the reranker's own
  numeric noise (a design error in this gate);
- no arm reuses a prefix (`cached n_tokens = 0` throughout: the server treats the
  bidirectional encoder correctly);
- all three arms differ from each other by the same amount (|difference| median
  0.014–0.017, p99 0.074–0.088, max 0.120–0.127, R1 against R2 included), so no
  configuration is the outlier a defect would make; it is batch-shape arithmetic, as in
  X39 step 2;
- every swap is between candidates at most 0.16 apart (R1 against R0: 0.11); the top-8 set
  that production passes on is the same in 96 (R1) and 98 (R2) of 100 calls.

So no reranker setting changes by rule. The choice goes to the user with the quiet runs
below, which measure without `-v` (all through the shared client): **R0q**, today's line
again, whose scores against R0 show whether the server repeats itself; **R0p**, today's line
plus `--cache-ram 0`, which must give R0q's scores exactly (it only stops saving idle
slots); **R1p**, R1 plus `--cache-ram 0`, for its real latency. The embedder's quiet runs
(E0q, E1p) are as amendment 1 set.

## Results (29 September)

**Sizing:** the longest embedding input is 1,102 tokens (`S_e` = 2,048); the longest
rerank input 748 (`S_r` = 1,024). Production before the arms: embedder 3,309 MiB of GPU
and 53 retries in its log; reranker 525 MiB and none; generator 3,141 MiB.

### Embedder (1,845 passages of version 11 in batches of 16; 50 queries)

| Arm | Retries | Lowest cosine vs E0 | GPU after load | Part (a) s | Query p50 / p95 s | (c) s | Peak private RAM |
|---|---|---|---|---|---|---|---|
| E0 (today) | **16** | — | 3,309 MiB | 246.6 | 0.498 / 0.773 | 10.2 | 13.4 GB |
| E1 `-np 1` | 0 | 0.99991 | **3,028 MiB** | **102.4** | 0.461 / 0.708 | 7.7 | 4.4 GB |
| E2 `-np 4 --no-kv-unified` | 0 | 0.99992 | 3,819 MiB | 217.2 | 0.465 / 0.692 | 7.6 | 14.0 GB |

**Kept: E1** (`--embedding --pooling last -np 1 -c 2048 -b 2048 -ub 2048`). E0 fails item 1
(it reproduces production's fault and its 3,309 MiB exactly); E1 and E2 are eligible and E1
is lowest by 21%. Ingestion is 2.4× faster: no retries with halved batches.

**Found while measuring (reported, not gated):**
- **Today's embedder fills an 8 GiB host prompt cache with slot states it never reuses.**
  With several slots, each idle slot is saved to the cache when another task starts
  (`--cache-ram` defaults to 8 GiB): E0 ended with 291 entries, 8,168 MiB, and 13.4 GB of
  private RAM for a 1.2 GB model. E1 saved none. `--cache-ram 0` belongs on both support
  servers, whatever their slots.
- **Most of the embedder's GPU memory is logits nobody reads.** Its compute buffer is
  1,201 / 600 / 300 MiB at `-ub` 2,048 / 1,024 / 512 (load-only probes): 614,880 bytes per
  token, the vocabulary logits (151,669 × 4 bytes) plus the hidden state. Pooled embeddings
  output every token, so the LM head runs on all of them; upstream describes the same waste
  for Qwen3.5 in draft [PR #28949](https://github.com/ggml-org/llama.cpp/pull/28949) (no
  fix for `qwen3` at b10298). Until upstream fixes it, `-ub` sized to the longest input
  (1,280 instead of 2,048) would free ~450 MiB, at the cost of failing inputs that grow
  past it; a later decision with its own check.
- **A query costs 77 ms on the server but ~460 ms through `llm.embed`.** Each `httpx.post`
  builds a new client, which loads the certificate bundle: ~410 ms per call on this laptop
  even for plain HTTP (a reused client: 0.4 ms). The answer path pays it on every model
  call. Fixed after the arms (a shared client), so the arms stay comparable.

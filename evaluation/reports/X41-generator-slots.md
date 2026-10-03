# X41. The generator: batch threads and a second slot

Design and gate written on 29 September 2026, before any run (PLAN §0i; the serving plan
was approved with X41 included). It reuses X39's setup, replay set and gate
(`evaluation/reports/X39-generator.md`).

## Question

X39 (D95) settled one slot with 8 threads. Two questions remain from the serving research:

1. Does prompt processing, with the experts on the CPU, get faster with 16 batch threads
   (`-tb 16`; the load log shows `n_threads = 8 (n_threads_batch = 8) / 16`)?
2. Does a second slot keep the understanding and answering prefixes resident, and serve
   two customers at once, within memory? Today a second customer waits for the first
   answer to finish.

## What the source says (b10298), read before any run

The approved plan had a third check and a different second arm. Reading the server at our
build (`tools/server/server-context.cpp` at tag b10298; `llama-server --help`) changed both:

- **Checkpoints are made at fixed places,** not up to the cap: at the start of the last
  user message, at user-message starts at least `--checkpoint-min-step` (8,192) tokens
  apart, and `4 + n_ubatch` and 4 tokens before the prompt's end
  ([PR #20288](https://github.com/ggml-org/llama.cpp/pull/20288)). Our requests hold one
  user message and at most ~12.5k tokens, so each makes 2 (understanding) or 3 (answering)
  checkpoints, far below the cap of 32. A prompt-cache entry is then about (checkpoints +
  1) × 62.8 MiB of recurrent state plus 20 KiB per token: 222 MiB and ~300 MiB, as X39's
  logs show. **`--ctx-checkpoints 8` cannot change anything here: dropped, no run.**
- **A unified KV buffer clears idle slots.** With `--cache-idle-slots` (default on), an
  idle slot is saved to the host prompt cache when a new task starts, and with
  `--kv-unified` it is then cleared from the GPU ([TAG_IDLE_SLOT_CLEAR]); without it the
  slot keeps its cache on the GPU. The plan's `-np 2 --kv-unified -c 32768` would not keep
  two prefixes resident. **The arm is `-np 2 --no-kv-unified -c 32768`:** each slot gets
  its own 16,384 tokens (the 32-passage budget fits), so slots cannot oversubscribe a
  shared buffer (X40's fault).
- **A request goes to the idle slot sharing the longest prefix** with it, when that share
  exceeds `--slot-prompt-similarity` (0.10). An answer request (~2,500 tokens) shares its
  ~341-token system prompt with the previous one (~14%), so it returns to that slot and
  resumes from the checkpoint at its user message; understanding requests share more
  with each other.

## Setup

As X39: 8080 and the 8090 page stopped (approved with the plan); the embedder, the
reranker and Postgres keep running; a scratch server on 127.0.0.1:8083 with the key from
`.env`, the same binary and model, and the live 8080 flags (D95) except the port and the
setting under test; `-v` on every load; a warm-up request after every start; logs in
`data/runs/x41/`. Afterwards 8080 and 8090 are restarted by the startup script and
checked (`/health`, an answer through 8090). The startup line changes only with the
user's OK.

`K` is the live configuration. Memory as X39 (GPU total every second, peak; the server's
private bytes and working set; minimum available memory), plus the server's own GPU
memory from `GPU Process Memory(pid)\Dedicated Usage` after each pass.

## Steps, in order

1. **`K-A`**: R40 (X39's 40 replayed answer requests), one at a time, `cache_prompt`
   false, `--cache-ram 0` (X39 amendment 2).
2. **`tb16`**: `K` plus `-tb 16`, the same pass.
3. **`K-B`**: `K` again. `K-A` and `K-B` must give the same 40 replies; |B − A| is this
   session's noise.
4. `K'` = `K`, plus `-tb 16` if kept.
5. **Reuse, `K'`**: X39's M4 arm w4-interleaved (conv-v1 understanding stand-ins, each
   followed by an R40 answer request with `max_tokens` 1), `cache_prompt` true,
   `--cache-ram 2048` (live).
6. **`np2`**: `K'` plus `-np 2 --no-kv-unified -c 32768`: (a) R40 one at a time as step 1;
   (b) the reuse pass of step 5; (c) R40 two at a time (`cache_prompt` false), timed from
   the first request to the last reply.

## Gate (fixed before any run)

**`-tb 16`** is kept by X39's M2 gate against `K-A`: the same replies (identical, or a
numeric difference as X39 amendment 3 reads it); GPU peak ≤ 7,680 MiB (all processes) and
≥ 8,192 MB available throughout; faster beyond noise (the 95% interval of the paired
difference in seconds per answer, prompts resampled, 10,000 draws, seed 39, wholly below
0, and the mean saving larger than |`K-B` − `K-A`| and X39's 0.108 s).

**`-np 2`** changes how the server behaves under load, so it is recommended to the user,
never adopted by rule. It is recommended only if all hold:

1. one at a time, the same replies as `K'` (as above) and not slower: the mean paired
   difference at most the noise above;
2. memory as above, throughout (b) and (c);
3. reuse: understanding requests' reused share on later turns within 0.02 of `K'`, and
   answer requests' reused share higher than `K'`'s;
4. two at a time: all 40 replies in at most 0.9 × the time `K'` takes one at a time
   (step 1 or 3's sum).

**Amendment 1 (before any run).** X40 found that `-v` prints every prompt-cache entry at
every save, so its cost grows with the cache and distorts timings. Timed passes here run
without `-v`; the buffer sizes come from separate load-only starts with `-v` (no requests),
one for `K` and one for `np2`.

Reported beside the gate: per-request seconds two at a time (median, p95); how many of
the 40 replies differ from one-at-a-time replies (the server is not batch-invariant, so
an answer may depend on what else runs), with their verified outcomes (status, claims
kept and removed); KV, recurrent-state and compute buffers from the load log.

## Results (29 September)

**Steps 1–3, `-tb 16`** (R40 one at a time, `--cache-ram 0`; the embedder and reranker on
their old lines throughout):

| Pass | Prompt tok/s | Output tok/s | s per answer | GPU peak (all) | Min available |
|---|---|---|---|---|---|
| `K-A` | 524 | 30.1 | 13.12 | 6,477 MiB | 16.1 GB |
| `tb16` | 522 | 30.5 | 13.01 | 6,477 MiB | 16.3 GB |
| `K-B` | 524 | 30.8 | 12.91 | 6,477 MiB | 16.5 GB |

`K-A` and `K-B` gave the same 40 replies, and so did `tb16`. `tb16` − `K-A` = −0.106 s
[−0.212, −0.010], smaller than this session's noise |`K-B` − `K-A`| = 0.202 s (and X39's
0.108 s). **Not kept:** prompt reading, the step batch threads serve, did not move (522
against 524 tokens/s), since with 2,048-token micro-batches the CPU-held experts are
copied to the GPU and multiplied there. `K'` = `K`. (`K-A` shared the CPU briefly with a
12-second test run, which may be part of why it was the slowest pass.)

**Step 6, two slots** (`np2` = `K` + `-np 2 --no-kv-unified -c 32768`). Load-only logs:
KV 320 → 640 MiB (two 16,384-token shares), recurrent state 62.8 → 125.6 MiB, compute
buffers unchanged (518 MiB GPU, 96 MiB host); the server's own GPU 3,091 → 3,473 MiB.

| Gate item | `K'` | `np2` | Holds |
|---|---|---|---|
| 1. One at a time: replies; s per answer | — | 40/40 identical to `K-A` and `K-B`; −0.23 s against `K-A`, −0.03 [−0.10, +0.05] against `K-B` | yes |
| 2. GPU peak (all processes); min available | 6,509 MiB; 14.8 GB | 6,891 MiB; 14.4 GB | yes |
| 3. Understanding reuse, later turns; answer-request reuse | 0.465; 0.007 | 0.465; **0.149** | yes |
| 4. All 40 answers, two at a time | 535–542 s one at a time | **452 s** (0.84–0.85) | yes |

- **Why answers get faster, not just busier:** with two slots each request type keeps its
  own checkpoint on the GPU, so an answer request resumes after its ~341-token system
  prompt: its prompt reading fell from 4.27 to 2.83 s (M4's interleaved pattern, 86 answer
  requests). Fewer new tokens also means one 2,048-token micro-batch instead of two for a
  typical ~2,300-token answer prompt, so the CPU-held experts are copied to the GPU once.
- **Two customers at once:** per request, median 20.6 s and p95 41.3 s (one at a time 12.5
  and 20.8 s): the two share the GPU and the CPU-held experts (output 15.3 tokens/s each,
  30.6 together, the same as one alone). One slot under the same load, simulated from
  `K-A` and `K-B`'s own service times (two clients, one queue): median 25.0–25.2 s, p95
  39.6–40.1 s, 517–525 s in all. So two slots cut the median wait by ~4.5 s and finish the
  load 14% sooner, at an equal p95.
- **Answers under concurrent load are not reproducible:** 22 of the 40 replies sent two at
  a time differ from the same requests sent alone; verified, 11 keep or remove different
  claims and 1 changes status (a771, refused alone, answered with one claim beside
  another request). This is the batch-shape arithmetic X39 (step 2) and A5 measured (at
  most 2 verdicts per set), now depending on what else is running.

## Conclusion (29 September 2026)

`-tb 16` is not kept (not faster beyond noise). **Two slots meet every condition for a
recommendation**: identical replies one at a time, memory within the limits (+382 MiB GPU),
answer requests ~1.4 s faster through prompt reuse, and 14% more answers per minute under
two concurrent users. The costs are the memory, and answers that depend on concurrent
traffic, as the reranker's did before D96. Proposed line (needs the user's OK):

    -m models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 32768 -np 2 --no-kv-unified -ngl all
    --n-cpu-moe 40 --fit off --load-mode none -b 2048 -ub 2048 --cache-ram 2048
    --cors-origins localhost --port 8080

Afterwards 8080 was restarted on today's line (unchanged) and 8081/8082 on D96's lines:
all healthy; own GPU 3,091 / 2,675 / 463 MiB; 18.2 GB available; the 8090 page answered
end to end in 11.3 s.

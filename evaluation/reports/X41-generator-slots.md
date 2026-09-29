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

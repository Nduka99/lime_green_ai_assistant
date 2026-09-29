# Serving the models

How the three model servers run on the laptop, what uses their memory, what to expect from
prompt caching, and the checks to make before any serving change. Everything here was
measured on this machine (llama.cpp build b10298, CUDA; Ryzen 7 7840HS, 8 cores; RTX 4060
Laptop, 8 GB; 64 GB RAM) unless a source is cited. Decisions: D95 (generator), D96 (support
servers). Experiments: `evaluation/reports/X39-generator.md`, `X40-support-servers.md`.

The servers are started at every Windows sign-in by `../lime-green-assistant/scripts/start-servers.ps1`
(outside this repo). A port already listening is left alone. Changes to that script need
the user's OK.

## The servers

| Port | Model | Role | Command line (after `-m`) |
|---|---|---|---|
| 8080 | Qwen3.6-35B-A3B UD-Q4_K_XL (22.4 GB) | understanding and answering | `-c 16384 -np 1 -ngl all --n-cpu-moe 40 --fit off --load-mode none -b 2048 -ub 2048 --cache-ram 2048` |
| 8081 | Qwen3-Embedding-0.6B f16 (1.2 GB) | query and passage vectors | `--embedding --pooling last -np 1 -c 2048 -b 2048 -ub 2048 --cache-ram 0` |
| 8082 | bge-reranker-v2-m3 Q8_0 (0.6 GB) | reranking search candidates | `--reranking -np 1 -c 2048 -b 2048 -ub 2048 --cache-ram 0` |

All three add `-ngl all --fit off --cors-origins localhost` and read their API key from
`LLAMA_API_KEY` (never on a command line).

**Why each generator flag (X39):**
- `--n-cpu-moe 40`: every layer's experts (≈20 GB) stay in main memory; attention, the
  shared expert and the KV cache sit on the GPU.
- `--load-mode none`: the weights are read once into pinned host memory (`CUDA_Host`,
  19.3 GB) instead of being mapped from the file; prompt reading 275 → 306 tokens/s.
- `-b 2048 -ub 2048`: to read a prompt, the CPU-held expert weights are copied to the GPU
  once per micro-batch; 2,048-token micro-batches need one or two copies per answer instead
  of five (306 → 525 tokens/s). 4,096 was no faster.
- `--cache-ram 2048`: the host prompt cache; the 8 GiB default left 3–5 GB of RAM free.
  2 GiB keeps all measured conversation reuse.
- `-c 16384`: room for 32 passages (≤ 10.4k tokens) plus a 2,048-token answer.
- `-np 1`: one request at a time (X41 measures two).
- Flash attention is on by default (`auto`). Speculative decoding is off: MTP needs another
  model file and was not exact under a JSON grammar; n-gram drafting was slower.

**Why each support-server flag (X40):**
- `-np 1`: automatic slots gave four slots on one shared buffer, which overflowed and
  retried (the embedder logged 53 retries). One slot also scores each input alone, so a
  vector or a rerank score never depends on what shared its batch (with four slots, 55 of
  101 rerank calls reordered near-tied candidates).
- `-c 2048 -b 2048 -ub 2048`: a pooled or ranked input must fit one micro-batch or the
  server refuses it; the longest inputs are 1,102 (embedding) and 748 tokens (rerank).
- `--cache-ram 0`: these servers never reuse prompts; with several slots the 8 GiB default
  filled with idle slot states (13.3 GB of RAM for the embedder).

## Memory: what takes it

**GPU** = model buffers + KV cache + recurrent state + compute buffers + CUDA pool peak.
- KV bytes per token = 2 (K and V) × attention layers × KV heads × head size × bytes per
  value. Generator: 2 × 10 × 2 × 256 × 2 = **20 KiB** (only 10 of its 40 layers keep one; the
  other 30 are Gated DeltaNet with a fixed state). Embedder: 2 × 28 × 8 × 128 × 2 = 112 KiB;
  reranker: 2 × 24 × 16 × 64 × 2 = 96 KiB (from the model configs; confirmed in X40's logs).
- Compute buffers grow with `-ub` (generator: 411 MiB at 512, 486 MiB at 2,048).
- **The CUDA pool grows to the largest batch the server ever ran and never shrinks**
  ([llama.cpp #23635](https://github.com/ggml-org/llama.cpp/issues/23635)): a server's GPU
  memory after a burst is its new floor. Bound each server's largest batch, and read memory
  after a worst-case load, never at idle.
- Desktop applications use the GPU too: read per-process numbers, not totals.

Generator on the GPU (X39 M1, after load, `-ub 2048`): 5,024 / 5,216 / 5,600 / 6,368 MiB
total at `-c` 8k / 16k / 32k / 64k; its own share at 16k is ≈3.1 GB.

**RAM** = CPU-held weights (pinned, not pageable, with `--load-mode none`) + host compute
buffers + the host prompt cache + process overhead. Generator ≈ 22–25 GB private.

## Slots and context: set them explicitly

With `--parallel` on auto, llama-server makes 4 slots, promises **each** the full `-c`,
and backs all four with one unified buffer
([lemonade #3276](https://github.com/lemonade-sdk/lemonade/issues/3276)). Concurrent inputs
then oversubscribe it: "failed to find free space in the KV cache", and the server retries
with halved batches. Always set `-np`, and either run one slot or give each slot its own
share (`--no-kv-unified`, `-c` = slots × the longest input). A pooled embedding or rerank
input must also fit in one micro-batch (`-ub` ≥ its tokens).

## Prompt caching: what to expect

- A request's prompt is reused only up to the first token that differs from a cached
  prompt ([vLLM design](https://docs.vllm.ai/en/latest/design/prefix_caching.html)). Put
  static text first (instructions), then data, then the question; never put timestamps or
  ids early.
- With one slot, the slot keeps its last prompt; the host cache (`--cache-ram`) keeps
  earlier ones (`--cache-idle-slots`, on by default).
- **A hybrid model resumes only from a saved state (checkpoint).** Its Gated DeltaNet
  layers cannot be rolled back, so a new prompt resumes from the latest checkpoint at or
  before its first differing token. b10298 (`tools/server/server-context.cpp`) saves them
  only at the start of the last user message, at user-message starts at least
  `--checkpoint-min-step` (8,192) tokens apart, and `4 + n_ubatch` and 4 tokens before the
  prompt's end ([PR #20288](https://github.com/ggml-org/llama.cpp/pull/20288)). Our
  requests make 2–3, far below `--ctx-checkpoints` (32).
- **Entry size** ≈ (checkpoints + 1) × 62.8 MiB of fp32 recurrent state + 20 KiB per
  token: ≈222 MiB for an understanding request, ≈300 MiB for an answer request (X39 logs).
  A 2 GiB cache holds about seven.
- **So text inside one message is never partly reused.** X39 M4's stand-in held the
  history inside the last user message: each later turn reused only the system prompt and
  processed the history again (≈1 s for 250 tokens). Previous turns sent as their own
  messages, with a window that does not slide, would leave a checkpoint near the end of the
  last prompt to resume from (X36's design question). History never goes into the long
  answer request.
- **With `--kv-unified`, an idle slot is cleared** from the GPU when another task starts
  (after being saved to the host cache); with `--no-kv-unified` it stays.

## Known upstream issues (checked against b10298)

| Issue | Effect here |
|---|---|
| [#22384](https://github.com/ggml-org/llama.cpp/issues/22384) checkpoint restore, hybrid models | b10298 restores the latest checkpoint before the first differing token (a workaround in the server); X39 M4 saw it work at the last user message |
| [#23635](https://github.com/ggml-org/llama.cpp/issues/23635) CUDA pool never shrinks | GPU floor ratchets up after large batches |
| [#27442](https://github.com/ggml-org/llama.cpp/issues/27442) empty completions above ~16–19k tokens (Metal) | not seen on CUDA up to 18.7k (X39 M3) |
| MTP with `--mmproj` unsupported | MTP excluded while images are planned (S4) |
| Pooled embeddings run the LM head on every token ([draft PR #28949](https://github.com/ggml-org/llama.cpp/pull/28949), Qwen3.5 only) | the embedder's compute buffer is ≈0.59 MiB per `-ub` token of unread logits: 1.2 GB at 2,048 (X40) |
| `--cache-ram` defaults to 8 GiB on every server, embedding and reranking included | with several slots, idle slot states fill it unused: 13.4 GB of RAM for the embedder (X40); set `--cache-ram 0` on support servers |

## Before any serving change or measurement

1. **Pre-flight:** list every `llama-server` with its command line and port (below); stop
   anything left over. A stopped tool call can still have started a server.
2. **Read the flags you are not changing:** anything that caches, slots, context, batch.
3. **Attribute memory by component** from the load log (`-v` for buffer sizes) before
   forming a hypothesis.
4. **Measure through the production path** (the chat endpoint with the production body,
   `llm.embed`, `llm.rerank`), never a look-alike endpoint.
5. **Load, then measure:** memory after a worst-case batch; per-process GPU counters.
6. **One change at a time,** each against the configuration kept so far; run the baseline
   twice to know the noise.
7. **Write the gate first** (an experiment report), record the build, and restore every
   server with the startup script afterwards: `/health` 200 on each, one end-to-end answer.

## Commands

List the model servers:

    Get-Process llama-server | ForEach-Object { "{0} {1}" -f $_.Id,
      (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine }

GPU memory per process (Windows; `nvidia-smi` shows N/A per process under WDDM):

    (Get-Counter "\GPU Process Memory(*)\Dedicated Usage").CounterSamples |
      Where-Object CookedValue -gt 50MB | ForEach-Object {
        if ($_.InstanceName -match "pid_(\d+)") { "{0} {1:N0} MiB" -f
          (Get-Process -Id $Matches[1]).ProcessName, ($_.CookedValue / 1MB) } }

Free memory: `(Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue`.
Health: `curl http://127.0.0.1:8080/health` (and 8081, 8082); the platform's readiness:
`/readyz` on the API.

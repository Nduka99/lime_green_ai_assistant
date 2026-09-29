# X39. The generator: memory, speed per setting, degradation and prompt reuse

Design and gate written on 29 September 2026, before any scratch server was started
(PLAN §0h, D92).

## Question

The generator's settings were inherited from the development repo, not researched:
Qwen3.6-35B-A3B (`models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`) served by llama.cpp b10298
as `-c 8192 -np 1 -ngl all --n-cpu-moe 40 --fit off`, with the defaults `-b 2048 -ub 512`,
flash attention `auto` and the model memory-mapped (the load log warns that CPU-held
tensors want `--no-mmap`). The model's native context is 262,144 tokens, but nothing
published says where its answers degrade, and an answer spends most of its time writing
(about 2,500 prompt tokens at 260–320 tokens/s, then 400–500 output tokens at 29–30
tokens/s). How much memory does each context size take, which settings make answers
faster without changing them, how many passages can one answer request hold before the
model stops using the evidence, and how much of each chat turn's prompt is reused?

## Setup (fixed for every measure)

- **Servers.** The generator on 8080 and the 8090 page are stopped (approved with the
  plan). The embedding (8081) and reranking (8082) servers and Postgres keep running, as
  in production, so memory is measured beside them. A scratch llama-server listens on
  127.0.0.1:8083 with the model servers' key (from `.env`, as `LLAMA_API_KEY`), the same
  binary and model, and today's 8080 flags except the port and the setting under test.
  Its logs go to `data/runs/x39/`. Afterwards 8080 and 8090 are restarted by the Windows
  startup script and checked; the startup command changes only with the user's OK.
- **Requests** are built by the same code as production (`answer.ANSWER_PROMPT`,
  `answer.user_prompt`, `answer.answer_schema`) and sent with `llm.chat`'s body:
  temperature 0, seed 42, `max_tokens` 2048, the JSON schema, thinking off. Timings are
  the server's own per request (`prompt_n`, `prompt_ms`, `cache_n`, `predicted_n`,
  `predicted_ms`, and draft counts when speculating).
- **Memory** is read while each pass runs: total GPU memory used (`nvidia-smi`, every
  second, peak), the scratch server's working set and private bytes, and available
  physical memory (Windows `\Memory\Available MBytes`, minimum).
- **Warm-up.** After every start, one untimed request (a prompt outside the replay set)
  before any timed one, so the first request's page-in is not counted.

## M2. Speed per setting (measured first)

- **Replay set R40:** 40 answer requests rebuilt from the audit records of S2's candidate
  run (version 11: the records named in `data/runs/{frozen90,heldout-v2,heldout-v3}/
  answers-s2-candidate.json`). Records with status `answered` or `insufficient_evidence`
  are sorted by answer id and 41 drawn with seed 39: the first is the warm-up, the other
  40 are R40. Each prompt is the recorded question with the recorded passages in the
  recorded order. Requests are sent with `cache_prompt: false`, so every request
  processes its whole prompt: timings are comparable and outputs do not depend on the
  order of requests (prompt reuse is M4's subject).
- **Ladder, one change at a time,** each step compared with the configuration kept so far:
  1. `base`: today's command. Run first (pass A) and again last (pass B).
  2. `-b 2048 -ub 2048`.
  3. `-b 4096 -ub 4096`.
  4. `--load-mode none` (no memory map; `--no-mmap` is deprecated in b10298).
  5. `-fa on`, only if the base load log shows `auto` did not enable flash attention;
     otherwise recorded as a no-op and skipped.
  6. `mtp-file`: the kept configuration on `models/Qwen3.6-35B-A3B-MTP-GGUF/
     Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` without speculation, to separate the file from the
     speculation. If its outputs are not identical to the kept configuration's, the MTP
     file holds different weights: MTP is then measured for speed but cannot be adopted
     without a quality evaluation of its own.
  7. Speculation, each arm against its own file's configuration without speculation:
     `--spec-type draft-mtp --spec-draft-n-max` 1, 2 and 3 (MTP file); `--spec-type
     ngram-simple --spec-draft-n-max 64` and `--spec-type ngram-map-k --spec-draft-n-max
     64` (base file; the documented example, other n-gram sizes at their defaults). If the
     MTP layer's experts push GPU memory past the gate, the MTP arms use `--n-cpu-moe 41`.
     Among the arms that pass, the one with the lowest mean seconds per answer is kept;
     arms within noise of each other → the one with no file change, then fewer drafts.
- **Measures per step:** prompt tokens/s, generation tokens/s, draft tokens and accepted
  drafts, seconds per answer (`prompt_ms + predicted_ms`), load time, peak GPU memory,
  the server's peak working set and private bytes, minimum available memory.

### Gate for a step (written before any run)

A step is kept only if all three hold:

1. **Same answers.** Every reply finishes (`stop`) and matches the schema, and each of
   the 40 replies is identical to the kept configuration's, or its difference is
   numeric: llama.cpp is not batch-invariant, so a change of batch shape can flip a
   near-tie. A difference is read as numeric when, at the first differing token, the
   kept configuration's two most likely tokens (its chosen token and the step's) are
   within 0.5 nats of each other, read with `n_probs` from the kept configuration given
   the prompt and the common prefix. Any other difference is a defect: the step is not
   kept until it is diagnosed. Differing replies are reported with their verified outcome
   (status, claims kept and removed by `verify`).
2. **Memory fits beside the other servers:** peak GPU memory ≤ 7.5 GB (all processes)
   and available physical memory ≥ 8 GB throughout the pass. GB here is the card's own
   unit (its "8 GB" is 8,188 MiB in `nvidia-smi`): 7,680 MiB and 8,192 MiB (clarified
   before any run; with today's 8080 serving, the GPU held 7,022 MiB and 10,656 MB of
   memory was available, desktop applications included).
3. **Faster beyond noise:** over the 40 prompts, the 95% interval of the mean paired
   difference in seconds per answer (step − kept; prompts resampled, 10,000 draws, seed
   39) lies wholly below zero, and the mean saving is larger than the absolute mean
   difference between the base passes A and B. Where replies differ, their seconds are
   compared per token and reported beside the gate.

Pass A against pass B also shows whether the server repeats itself: 40 identical replies
are expected; anything else is reported and diagnosed before the ladder is read.

## M1. Memory per context size (on M2's kept configuration)

- Loads at `-c` 8192, 16384, 32768 and 65536, each read from a verbose load log (`-v`,
  no requests): KV cache buffer, recurrent-state buffer, compute buffers (GPU and host),
  model buffers; and the GPU memory and server memory after load.
- Checked against the arithmetic: 10 attention layers × 2 KV heads × 256 dimensions ×
  (K + V) × 2 bytes ≈ 20 KB per token.
- R40 replayed once at `-c 8192` with prompt reuse on (`cache_prompt` true, `--cache-ram`
  default 8 GiB): the prompt cache's entry sizes and total from the log, checkpoints per
  prompt, and the server's peak memory.
- Reported, not gated; M3's context size must pass M2's memory gate.

## M3. Where the answers degrade: passages per request and the evidence's position

- **Questions:** the dev sets (frozen90, held-out v2, held-out v3; held-out v4 is never
  used), one wording per case (`original`), cases the key expects answered. Every text
  evidence quote must be found by `find_quote` in some searchable passage of version 11;
  the evidence set E is, for each quote, the passage holding it that ranks best in the
  question's own ranking (below). Cases with more than 4 evidence passages are left out,
  so 8 passages keep at least half distractors. All eligible cases are used (at most 34).
- **Distractors:** the question's own search over version 11 as `store.search` does it,
  with 100 candidates per method, fused, then the top 100 reranked; distractors are that
  order without E and without any passage holding a key quote of the case, so no
  distractor holds its evidence. The first n − |E| are taken: the hard, same-subject
  distractors a real search returns.
- **Arms:** n ∈ {8, 16, 32, 64} passages × evidence position ∈ {first, middle, last}: E
  in its own order at the start, after the first ⌊(n − |E|)/2⌋ distractors, or at the
  end. Source ids S1…Sn follow the layout. Twelve requests per question, on M2's kept
  configuration, at the smallest `-c` of 16384, 32768 or 49152 that holds the longest
  prompt plus 2,048 output tokens (n = 64 is dropped and reported if that context fails
  M2's memory gate).
- **Measures per request:** the reply finishes and parses; the verified outcome
  (`verify`): status, claims kept and removed; **evidence used**: for each evidence
  passage, whether a kept claim quotes it.
- **Primary curve:** the share of evidence passages used, by n (positions pooled) and by
  position within n, with 95% intervals from resampling questions.
- **Passage budget (rule fixed now):** the largest n whose paired difference from n = 8 in
  evidence passages used (same questions and positions; questions resampled, 10,000
  draws, seed 39) has a 95% interval with its lower bound above −0.10, and every smaller
  n too (clarified with the harness code, before any run). This bounds how
  many passages S2 round 2's ladder may give one answer request; it does not say more
  passages help, because here the evidence is always present (recall is the ladder's
  own measure).

## M4. Prompt reuse per chat turn (on M2's kept configuration)

- **Conversations:** conv-v1, 20 conversations and 86 turns, with history in reference
  mode as X36 registered it (each earlier turn's message and reference reply; the fixed
  referral after an emergency turn).
- **Understanding request (stand-in):** the understanding request with history is built
  with X36; its reuse pattern depends on where the history sits, so the stand-in keeps
  that: system `EXPOSURE_PROMPT`, then one user message holding the last w turns
  (`Customer: …` / `Assistant: …`) and the new message, with `EXPOSURE_SCHEMA`.
- **Arms:** w ∈ {2, 4} × `alone` (understanding requests only, turn by turn) or
  `interleaved` (each followed by an answer request from R40, in order, with
  `max_tokens` 1, as production follows understanding with answering in the one slot).
  Prompt reuse on (`cache_prompt` true), server defaults for the prompt cache and
  checkpoints.
- **Measures per turn:** prompt tokens, tokens processed (`prompt_n`), tokens reused
  (`cache_n`), prompt seconds; by w, arm, and first against later turns; prompt-cache
  and checkpoint lines from the log. Reported, not gated: it sets the cost of X36's
  history window.

## Sampling

Greedy decoding stays (reproducible JSON, and M2's identity check depends on it). Qwen's
recommended non-thinking sampling (temperature 0.7, top-p 0.8, presence penalty 1.5) is
a later experiment with its own gate, not a default change.

## After the runs

- The kept configuration becomes a proposed startup command, changed only with the
  user's OK (`../lime-green-assistant/scripts/start-servers.ps1`), and with the MTP file
  only if MTP is kept. Known limit: llama.cpp does not yet run MTP with `--mmproj`, which
  S4 (multimodal generation) needs; that choice is S4's.
- The passage budget and context size go to PLAN §0h and S2 round 2 (B, A5, C ladder),
  which then runs on the settled settings.

## Amendment 1 (29 September, after M2 steps 1–3, before any later step)

**Found.** Every memory-mapped configuration, today's included, leaves 3.1–3.3 GB of
memory available during a pass, against the 8 GB floor of gate item 2. The server's
working set reaches 29.8 GB: 12.4 GB private (the CPU backend's repacked copies of
expert tensors; 13.8 GB at `-ub 2048`, 15.7 GB at `-ub 4096` as host compute buffers
grow) beside about 17 GB of the mapped file still resident. With the generator stopped,
about 31 GB is available. Steps 2 and 3 therefore fail item 2 as written, as today's
settings would; the cause is the memory map, not the batch size.

**Re-ordered.** Step 4 (`--load-mode none`, which the load log itself recommends) removes
the mapped copy, so it runs next, on the base configuration. If it is kept, steps 2 and 3
run again on top of it and are judged by the same gate. Nothing else changes.

**Diagnosis reads deeper.** At the first token the schema's grammar forces tokens the
model ranks 25th–40th (it would start with prose), so reading 20 candidates left three
first-token differences without a lead. The diagnosis now reads 1,000; the 0.5-nat rule
is unchanged.

### M2 steps 1–3 as measured (40 prompts, `cache_prompt` false)

| Step | Prompt tok/s | Output tok/s | s per answer | Peak GPU MiB | Min available MB | Server private MB |
|---|---|---|---|---|---|---|
| 1 base (pass A) | 275 | 30.3 | 17.5 | 5,046 | 3,320 | 12,438 |
| 2 `-b 2048 -ub 2048` | 483 | 30.7 | 13.3 | 5,118 | 3,217 | 13,805 |
| 3 `-b 4096 -ub 4096` | 563 | 30.6 | 13.0 | 5,516 | 3,075 | 15,663 |

- Step 2 against 1: −4.12 s per answer [−5.40, −3.00]; 17 of 40 replies identical; all
  23 differences start at a near-tie (leads −0.56 to +0.36 nats, three of them at the
  first token: compact against indented JSON), so all are numeric. Every reply finished.
- Step 3 against 2: −0.30 s [−0.97, +0.46]: not faster beyond its interval.
- Load log (base, `-c 8192`): flash attention `auto` resolves to enabled, so step 5 is a
  no-op; KV cache 160 MiB (8,192 cells × 10 layers, f16: the predicted 20 KB per token);
  recurrent state 62.8 MiB; GPU compute buffer 411 MiB; model 2,039 MiB on the GPU and
  20,798 MiB mapped on the CPU.
- Idle GPU without the generator: 2,207 MiB (embedding and reranking servers, desktop).
- Output layout: 4–5 of 40 replies are indented JSON rather than compact; on a prompt
  answered both ways with the same content, indented took 320 output tokens against 239.
  Recorded for a later change (a compact-only grammar), not changed here.

## Amendment 2 (29 September, after step 4, before any later step)

**Diagnosed.** Step 4 (no memory map) gave the same 40 replies as step 1 and was faster
(−0.93 s per answer [−1.07, −0.82]; prompt 306 tokens/s), but still left only 4.2 GB
available: the server's private memory reached 31.7 GB. The memory is the host prompt
cache (`--cache-ram`, default 8 GiB), not the map: the server saves every finished
request's state there even when the request does not reuse prompts (the logs evict
287–361 MiB entries once 8 GiB is full, in every pass), and after a single request the
server's private memory was 4.2 GB. Amendment 1's diagnosis (the mapped copy) was wrong.

**Changed, before the runs it affects.**
- The remaining M2 steps run with `--cache-ram 0`. Their requests never reuse prompts
  (`cache_prompt` false), so the cache cannot change their timings or replies; the first
  such run (`nommap-c0`, step 4 again) checks this against step 4: identical replies are
  required.
- Steps 2 and 3 run again on top of the kept configuration, as amendment 1 set.
- The prompt cache's size becomes a setting of its own, chosen by M4: M4's interleaved
  arm with a 4-turn window runs at `--cache-ram` 8192 (the default), 2048 and 0 MiB; the
  chosen size is the smallest whose reused share of understanding-request tokens is
  within 0.02 of the default's. The final configuration, with that size, must pass gate
  item 2 in M1's replay.
- Pass B repeats pass A's configuration exactly (default cache), as registered.

## Amendment 3 (29 September, the diagnosis's method; the rule is unchanged)

The first diagnosis rebuilt the parting context by tokenising the replies' text, which
need not give the token ids the model generated, and it accepted any negative lead,
while the rule says the two tokens must be *within* 0.5 nats of each other. A reading of
−2.36 nats on MTP (the step's token far ahead of the kept configuration's own greedy
choice) showed the context was not the run's. The diagnosis now sends the kept
configuration the same chat request again, asking for each position's log-probabilities
(`logprobs`, 200 candidates), requires the reply to reproduce the kept reply exactly,
finds the token holding the first byte where the step's reply differs (and, when that
token starts exactly there, the token before it, which the step may have replaced with
a longer one), and compares the kept token with the most likely candidate consistent
with the step's text; numeric means |lead| < 0.5. Each reading keeps every position's
log-probability, so the same pair read on the step's configuration shows how far the
two configurations' arithmetic moves the model on the tokens both replies share.
(A regeneration through the completion endpoint, with the same prompt tokens and schema,
reproduced only 6 of 23 kept replies: the two endpoints do not generate identically, so
it was not used.) Every diagnosis is run again this way before the gate is read.

## Results

### M2. Speed per setting (40 replayed answer requests each)

| Pass | Prompt tok/s | Output tok/s | s per answer | Peak GPU MiB | Min available MB | Server private MB | Drafts accepted |
|---|---|---|---|---|---|---|---|
| base (A) | 275 | 30.3 | 17.5 | 5,046 | 3,320 | 12,437 | – |
| base (B, last) | 278 | 30.4 | 17.3 | 5,002 | 5,072 | 12,448 | – |
| no map | 306 | 30.6 | 16.5 | 4,995 | 4,189 | 31,730 | – |
| no map, cache off | 307 | 30.8 | 16.4 | 4,995 | 11,935 | 23,567 | – |
| + `-b/-ub 2048` | 525 | 30.5 | 13.0 | 5,067 | 11,354 | 24,898 | – |
| + `-b/-ub 4096` | 606 | 30.8 | 12.7 | 5,472 | 11,642 | 27,016 | – |
| MTP file, no drafts | 527 | 30.9 | 12.4 | 5,074 | 11,572 | 24,847 | – |
| MTP, 1 draft | 518 | 37.3 | 11.6 | 5,994 | 11,352 | 27,832 | 5,258 / 5,461 |
| MTP, 2 drafts | 518 | 41.0 | 11.0 | 6,058 | 11,382 | 27,873 | 7,010 / 7,530 |
| MTP, 3 drafts | 517 | 42.8 | 10.3 | 6,152 | 11,601 | 28,060 | 7,322 / 8,301 |
| n-gram simple | 525 | 21.4 | 16.8 | 5,108 | 11,700 | 25,168 | 2,777 / 12,438 |
| n-gram map-k | 524 | 27.3 | 14.1 | 5,106 | 11,629 | 25,191 | 708 / 3,506 |

**Repeatability and noise.** Passes A and B gave the same 40 replies; B − A = −0.108 s
per answer [−0.227, +0.005], so a step must save more than 0.108 s.

**Gate, step by step** (differences are step − kept, seconds per answer, 95% interval):

1. **No memory map** — same 40 replies as the base; −0.93 [−1.07, −0.82]; with the
   prompt cache off (amendment 2; the cache changed no reply and no timing: −0.07
   [−0.16, +0.03]) 11.9 GB stays available. **Kept.**
2. **`-b 2048 -ub 2048`** on top — −3.47 [−4.68, −2.40]; 11.4 GB available, GPU 5,067
   MiB. 23 of 40 replies differ. Read as amendment 3 sets out, every one reproduced;
   20 part within 0.5 nats. The other three: a955 and a783 choose compact or indented
   JSON at the first token (0.23–0.28 nats on the kept side, 0.75 on the step's), and
   a894 chooses which source to cite next (0.62 on the kept side, 0.38 the other way on
   the step's, so the gap moved about 1.0 nat). On the 2,150 tokens both replies share,
   the batch change itself moves log-probabilities by median 0.000, 99th percentile
   0.30, at most 0.96 nats: a gap moving by about 1 nat is this arithmetic, not a
   defect. All 23 are numeric. **Kept.**
3. **`-b 4096 -ub 4096`** — against step 2: −0.31 [−0.97, +0.46]. Not faster. Not kept.
4. **`-fa on`** — flash attention was already on. Skipped as registered.
5. **MTP file** — without drafts it gives 18 of 40 replies identical to the kept
   configuration's: its weights differ (header: the importance matrix has 77 chunks, not
   76; 5 tensors have other types; expert tensors differ byte for byte; the Q8_0 tensors
   are identical). By the registered rule MTP needs a quality evaluation of its own.
6. **MTP drafts** against the MTP file without drafts: 1 draft −0.84 [−1.47, −0.15];
   2 drafts −1.45 [−2.13, −0.77]; 3 drafts −2.14 [−2.81, −1.41] (against 2 drafts −0.68
   [−1.46, +0.05], within noise, so 2 would be chosen). But speculation is not shown to
   be exact under the schema's grammar in this build: for 2 drafts, 17 of 19 differences
   part within 0.5 nats, a894 is the 0.62-nat choice above, and a868 parts where the
   model without drafts leads by 14 nats (a reply it would not write); and the
   probabilities the server reports under speculation differ from the model's on shared
   tokens by up to 8.6 nats (99th percentile 4.3). **Not kept.** Any later MTP work must
   first show that speculation is exact under the grammar, then pass a quality
   evaluation of the MTP file; llama.cpp also cannot yet run MTP with `--mmproj` (S4).
7. **n-gram speculation** — slower: `ngram-simple` +3.82 [+2.73, +5.15] (22% of drafts
   accepted, drafts up to 64 tokens), `ngram-map-k` +1.14 [+0.68, +1.66] (20%). Checking
   a long draft costs more on this model, whose experts run on the CPU, than the
   accepted tokens save. Not kept.

**Kept configuration:** today's flags plus `--load-mode none -b 2048 -ub 2048`, with the
prompt cache sized by M4: 17.4 s → 13.0 s per answer (−25%), same model file, replies
numerically equivalent. The weights then sit in pinned host memory (`CUDA_Host` 19,275
MiB), which is why prompt processing speeds up.

### M1. Memory per context size (kept configuration, cache off, after load)

| `-c` | KV cache | Recurrent state | GPU compute | Host compute | GPU total | Server private |
|---|---|---|---|---|---|---|
| 8,192 | 160 MiB | 62.8 MiB | 486 MiB | 64 MiB | 5,024 MiB | 24,460 MB |
| 16,384 | 320 MiB | 62.8 MiB | 518 MiB | 96 MiB | 5,216 MiB | 24,687 MB |
| 32,768 | 640 MiB | 62.8 MiB | 582 MiB | 160 MiB | 5,600 MiB | 25,135 MB |
| 65,536 | 1,280 MiB | 62.8 MiB | 710 MiB | 288 MiB | 6,368 MiB | 26,034 MB |

The KV cache is exactly 20 KiB per token (10 attention layers × 2 KV heads × 256 × K and
V × 2 bytes), as predicted; the recurrent state is fixed. Even 65,536 tokens fit the GPU
limit (7,680 MiB) beside the other servers. M3's 64-passage prompts hold 10,085–18,703
tokens (median 16,318), so M3 runs at `-c 32768`.

### M4. Prompt reuse per chat turn (kept configuration, `-c 8192`)

conv-v1, 20 conversations, 86 turns; understanding stand-in with history in reference
mode. Tokens reused are the server's `cache_n`; prompt seconds are its own.

| Arm | Cache | First turns: prompt tokens / reused | Later turns: prompt tokens / reused | Understanding prompt s (later) | Min available MB |
|---|---|---|---|---|---|
| w2, alone | 8 GiB | 151 / 74.2% | 229 / 51.5% | 1.10 | 10,380 |
| w2, interleaved | 8 GiB | 151 / 74.2% | 229 / 51.5% | 1.10 | 6,250 |
| w4, alone | 8 GiB | 151 / 74.2% | 254 / 46.5% | 1.15 | 9,396 |
| w4, interleaved | 8 GiB | 151 / 74.2% | 254 / 46.5% | 1.15 | 6,085 |
| w4, interleaved | 2 GiB | 151 / 74.2% | 254 / 46.5% | 1.17 | 11,847 |
| w4, interleaved | off | 151 / 0% | 254 / 0% | 2.14 | 13,802 |

- **What is reused:** the system prompt (about 112 tokens) and little more. A later turn's
  history is processed again every turn (it reuses about 118 of 254 tokens): this
  hybrid model can resume only from saved states, and none is saved inside a short
  prompt. At these sizes that costs about a second per turn; a window of 4 turns costs
  0.05 s more than a window of 2.
- **The host cache restores the understanding prefix after an answer request:**
  interleaving answer requests changed nothing with a cache; without one, every
  understanding request is processed whole (2.1 s instead of 1.2 s).
- **Cache size (rule fixed in amendment 2): 2 GiB.** Its reuse equals the default's
  (46.5% on later turns); off loses it all. With 2 GiB, 11.8 GB stays available.
- **Reported, outside the rule:** answer requests reused 6.0% of their prompt with 8 GiB
  (the shared system prompt) but 0.7% with 2 GiB, so their prompt processing took 4.29 s
  instead of 3.76 s. 8 GiB fails the memory floor (6.1 GB available); 4 GiB, untested,
  might keep both and is left as an option.

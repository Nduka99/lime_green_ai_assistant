# Lime Green Assistant

A local LLM assistant that answers questions from Lime Green website pages,
shows the exact quote and page behind every factual claim the model writes, and
says clearly when the pages do not contain enough information to answer.

```text
question -> keyword + vector search -> reranking -> local LLM
         -> quote, number and regulation checks -> answer with sources
```

## Example answers

Real output from the shipped setup (Qwen3.6-35B-A3B on an 8 GB laptop GPU), one
question for each kind the brief asks to test. Links are shortened here; each
opens the live page at the quoted sentence.

**Straightforward:** `uv run limespec ask "Does Duro lime render base coat contain any cement?"`

```text
Answer:
1. Duro lime render base coat is completely free of cement. [1]

Sources:
[1] Duro Lime Render Base Coat › Duro Lime Render Base Coat (captured 2026-09-12)
    "Duro lime render is completely free of cement, gypsum, acrylic, ash and Pulverised Fuel Ash (PFA), so is perfectly compatible with traditional building techniques."
    https://www.lime-green.co.uk/products/lime-render/duro#:~:text=Duro%20lime%20render…
```

**Several sources** (the brief's example question): `uv run limespec ask "What products are suitable for lime-based external finishes?"`

```text
Answer:
1. Lime Green offers lime-based external finishes suitable for base applications including timber frame, lightweight blocks, and brick, and they can be used with Ultra or Duro as the base coat. [1] [2]
2. Natural Finish is a self-coloured external lime render that requires no further painting. [3]
3. Finish WP is a specialist lime finish coat render for the Warmshell insulation system that offers protection against rain and other elements. [4] [5]

Sources:
[1] Lime Render › Lime Render (captured 2026-09-12)
    "We have a range of products to suit most base applications from timber frame to lightweight blocks, brick and more."
    https://www.lime-green.co.uk/products/lime-render#:~:text=We%20have%20a…
[2] Natural Finish Lime Render › Natural Finish Lime Render (captured 2026-09-12)
    "whether you use Ultra or Duro as the base coat."
    https://www.lime-green.co.uk/products/lime-render/natural-finish#:~:text=whether%20you%20use…
[3] Natural Finish Lime Render › Natural Finish Lime Render (captured 2026-09-12)
    "Natural Finish is self coloured external lime render requiring no further painting."
    https://www.lime-green.co.uk/products/lime-render/natural-finish#:~:text=Natural%20Finish%20is…
[4] Finish WP External Lime Render › Finish WP External Lime Render (captured 2026-09-12)
    "A specialist lime finish coat render for the Warmshell insulation system."
    https://www.lime-green.co.uk/products/lime-render/finish-wp#:~:text=A%20specialist%20lime…
[5] Finish WP External Lime Render › Finish WP External Lime Render (captured 2026-09-12)
    "Special additives in this external lime render offer the very best protection against rain and other elements."
    https://www.lime-green.co.uk/products/lime-render/finish-wp#:~:text=Special%20additives%20in…
```

This answer is supported but incomplete. It misses Tradirend, the third finish
coat, and its first claim joins a general line about the range to a Natural
Finish detail. Every model tested missed Tradirend; *Results* explains why.

**Insufficient information:** `uv run limespec ask "How much does a bag of Natural Lime Mortar cost, and do you offer free delivery?"`

```text
Answer:
I could not find enough support in the indexed Lime Green pages to answer this reliably. The closest pages are listed below; please contact Lime Green's technical team for project-specific advice.

Closest pages:
- Natural Lime Mortar: https://www.lime-green.co.uk/products/lime-mortar/natural-lime-mortar
- Lime Mortar: https://www.lime-green.co.uk/products/lime-mortar
- What Is Lime?: https://www.lime-green.co.uk/support/knowledgebase/what-is-lime
```

## How it meets the brief

| The assistant should | How | Where |
|---|---|---|
| Retrieve relevant information | Keyword search and vector search over 315 passages from 68 pages, merged, then a reranker orders the best 20; the model gets the top 8 | `ingest.py`, `retrieve.py` |
| Use a local LLM to answer | Qwen3.6-35B-A3B on llama.cpp returns short claims, each with the exact quote it relies on | `answer.py`, `llm.py` |
| Provide the sources | Every factual claim the model writes lists its page, section, quote, capture date and a link to the quote on the live page; refusals and safety referrals are fixed text | `verify.py`, `view.py` |
| Minimise unsupported information | Code checks every quote is in the cited passage, and every number and named regulation is in the quote; a failing claim is removed, never repaired | `verify.py` |
| Say when information is insufficient | The model reports what the pages cannot answer; the reader gets a fixed refusal and the closest pages, or a caution when only part is answered | `answer.py` |

The answer path is `answer.py` → `retrieve.py` → `verify.py`; the whole
application is about 1,400 lines in `src/limespec/`.

## Design decisions

- **Local only.** llama.cpp runs the generator, the embedding model and the
  reranker as three local servers; after the pages are fetched, nothing leaves
  the machine.
- **Qwen3.6-35B-A3B writes the answers.** It was the best of three local models on
  the frozen evaluation: 77 of 90 answers sound, against 74 for Gemma 4 26B-A4B and
  36 for Nemotron 3 Nano 4B, the small model deployed first. On 60 held-out
  questions asked through the live page, blind pairwise judging put Qwen and Gemma
  level and Nemotron behind, so Qwen stayed. It uses about 3 billion of its 35
  billion parameters per token, so its expert layers sit in system RAM while search
  stays on the 8 GB graphics card.
- **Two kinds of search, then a reranker.** Keyword search (SQLite FTS5) finds exact
  product names and vector search (Qwen3-Embedding 0.6B) finds the same idea in
  other words; reciprocal-rank fusion merges the two lists, and a cross-encoder
  (BGE v2-m3) reorders the best 20 so the answer passage comes first more often.
- **SQLite, not a vector database or RAG framework.** 315 passages fit in one file
  with no database service to run; every step is plain Python that can be read and
  tested.
- **Evidence checked by code, not trusted.** The model must quote; code decides what
  the reader sees. A claim whose quote, numbers or named regulations are not in the
  cited passage is removed, never repaired, and the reader sees a caution.
- **Fixed text where guessing is risky.** Refusals use fixed wording. A separate
  first model request checks whether the question describes an accident (a product
  swallowed, or in the eyes or on the skin); if it does, the reader gets fixed NHS
  and vet referral text and the model writes nothing.
- **Pages chosen by rule.** Every product, knowledge-base, FAQ, Warmshell, About and
  Contact page in the sitemap (68 pages), not pages picked to suit test questions.
  Fetching follows `robots.txt` and waits a second between requests.

## Constraints

- One laptop with an 8 GB NVIDIA GPU (RTX 4060) and 64 GB of RAM. Measured while
  answering, the three servers of the shipped setup use about 25 GB of system RAM
  (Qwen 21.3 GB, because its expert layers live there) and at most 6.3 GB of GPU
  memory, so another machine needs at least 32 GB of RAM and an 8 GB NVIDIA GPU.
- HTML pages only. Linked PDF data sheets, live prices and stock are outside the
  knowledge base.
- A time-limited exercise: a working, tested prototype, not a production service,
  and not a substitute for professional building or medical advice.

## Install

You need Python 3.12, a recent
[llama.cpp release](https://github.com/ggml-org/llama.cpp/releases) with GPU
support (tested with build b10298), and [uv](https://docs.astral.sh/uv/) or pip.
Put `llama-server` on your `PATH`. The tested setup used Windows, an 8 GB NVIDIA
GPU and 64 GB of RAM; the Python application itself has no platform-specific
paths.

One command installs everything: the application, its tests and the notebook.

```powershell
uv sync --all-groups --locked
```

Without uv, `requirements.txt` pins the same versions (generated from `uv.lock`):

```powershell
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

With pip, drop the `uv run` prefix from the commands below.

## Build the search index

Run every command from the repository root. Model files (`models/`), fetched
pages and the index (`data/`) stay on your machine and are never committed.

1. Download `Qwen3-Embedding-0.6B-f16.gguf` from
   [Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/tree/main),
   put it in `models/`, and start the embedding server:

   ```powershell
   llama-server -m models/Qwen3-Embedding-0.6B-f16.gguf --embedding --pooling last -c 2048 -b 2048 -ub 2048 -ngl all --fit off --port 8081
   ```

2. Fetch the pages listed in `sources.txt` (cached in `data/site/`, one second
   apart) and build the index in `data/limespec.db`:

   ```powershell
   uv run limespec ingest
   ```

3. See which passages a question retrieves (this also needs the reranker server
   from "Ask questions" below):

   ```powershell
   uv run limespec search "What is Grippa used for?"
   ```

## Ask questions

Answering needs three servers: the embedding server from step 1, the reranker
and the generator. Download `bge-reranker-v2-m3-Q8_0.gguf` from
[bge-reranker-v2-m3 GGUF](https://huggingface.co/keisuke-miyako/bge-reranker-v2-m3-gguf-q8_0/tree/main)
and `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf` (22.4 GB) from
[Qwen3.6-35B-A3B GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/tree/main).
Put both in `models/` and start each in its own terminal:

```powershell
llama-server -m models/bge-reranker-v2-m3-Q8_0.gguf --reranking -c 8192 -b 2048 -ub 2048 -ngl all --fit off --port 8082
llama-server -m models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 8192 -np 1 -ngl all --n-cpu-moe 40 --fit off --port 8080
```

`--n-cpu-moe 40` keeps every expert layer in system RAM, so the search models fit
beside Qwen on an 8 GB card. On a smaller machine, run the light option instead,
`NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf` (2.9 GB) from
[NVIDIA Nemotron 3 Nano 4B GGUF](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF/tree/main):
it replies in about 5 seconds but fully answers fewer questions (see *Results*).

```powershell
llama-server -m models/NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf -c 8192 -np 1 -ngl all --fit off --port 8080
```

Then ask on the command line, or run the web page:

```powershell
uv run limespec ask "What is Grippa used for?"
uv run limespec ask      # prompts "Ask a question:"
uv run limespec serve    # the page at http://127.0.0.1:8090 (--port to change)
```

The command line and the page call the same `assistant.ask()`, so they give the
same answer; the page's JSON endpoint, `/api/answer?q=...`, returns it too.

## Tests

```powershell
uv run pytest                  # 133 tests, 100% coverage, no servers or models needed
uv run pytest -m live --no-cov # the brief's three kinds of question, with the servers running
uv run ruff check . ; uv run mypy src tests
```

The offline tests use invented pages and a fake model, so they check the rules
themselves: quote matching, number and regulation checks, refusals, safety
routing, retrieval fusion and reranking, page parsing, and that the command line
and web page give the same answer.

## Results

`notebook/engine_evaluation.ipynb` shows the measurement behind each engine change,
then both evaluations below. It reads the small files in `evaluation/results/`,
opens on GitHub with its charts, and needs no models or GPU to run:

```powershell
uv run jupyter lab notebook/engine_evaluation.ipynb
```

In VS Code, open the notebook and choose the `.venv` Python environment as its
kernel.

**Held-out comparison (run last).** 60 new questions (12 cases, each asked five ways,
including rushed and misspelt wordings) were typed into the running web page one at
a time, for each model in turn. Judges compared two models' answers to the same
question against a locked answer key and chose the better one or a tie: two fresh
LLM chats that had never seen the project judged all 180 pairs, and a third settled
the 16 they decided differently. Bradley-Terry turns those verdicts into one
strength per model.

| Generator | Strength (log), 95% interval | Median time per answer |
|---|---|---|
| Qwen3.6-35B-A3B (shipped) | +0.18 (0.04 to 0.33) | 12.7 s |
| Gemma 4 26B-A4B | +0.18 (0.03 to 0.33) | 15.3 s |
| Nemotron 3 Nano 4B, 8-bit | −0.36 (−0.55 to −0.18) | 11.0 s |

Qwen and Gemma cannot be separated: Bradley-Terry gives each a 50% chance of beating
the other. The plan was to ship the strongest model. With an exact tie, I kept
Qwen, the model already shipped, and made that choice after seeing the result.
Times run from clicking Ask to the answer page; Gemma and Nemotron ran with only
part of their layers on the 8 GB card.

**Frozen evaluation (chose the model).** 90 questions (18 cases, each asked five
ways) whose expected answers were locked before the engine was built. Two blind LLM
judges graded every answer, and I settled their disagreements.

| Generator (same retrieved passages) | Sound / partial / wrong, of 90 | Median time per answer, search included |
|---|---|---|
| Qwen3.6-35B-A3B | 77 / 8 / 5 | 12.0 s |
| Gemma 4 26B-A4B | 74 / 10 / 6 | 14.0 s |
| Nemotron 3 Nano 4B | 36 / 23 / 31 | 5.2 s |

The readable record of these questions and expected answers is
`evaluation/questions.md`.

**What worked**

- No model-written claim reaches the reader without a quote that code found in the
  cited passage, and each quote opens on the live page in one click.
- In both evaluations every model sent every accident question to the fixed
  referral and refused every price question; on the held-out questions every model
  also refused the figure the site does not give, and no model followed an
  injected instruction.
- Reranking ranked the answer passage first for 34 of the 70 frozen questions
  that have one, against 27 without reranking.

**What did not**

- Nemotron 3 Nano 4B, the first model deployed, was sound on 36 of 90 frozen answers
  against 77 for Qwen on identical passages, and 16 of its 31 wrong answers refuse
  questions the pages do answer; that is why Qwen ships.
- Every model over-reassures on Building Regulations questions.
- Answers drawn from several pages are often incomplete: the external-finishes
  answer above misses Tradirend, because the search step never passes its
  description to the model.
- Some facts are outside the 68 indexed pages: 15 of the 60 held-out questions are
  answered only in image descriptions or on the sample-order, terms and colour
  pages, and the models mostly refused them.
- A method adapted from my thesis research (an evidence graph linking products
  across pages, with a cited summary of each product) brought the passages for 112
  of the 125 expected answer parts to the model, the same as search alone on the
  same pages, and indexing the whole website made search worse. Neither is in this
  submission.

**Next, with more time**

- Search each part of a many-part question separately. Tried after the frozen
  evaluation on questions built by joining evaluation questions, it raised the parts
  answered correctly from 10 to 14 of 18 (one grader), but made answers about 70%
  slower (median).
- With more graphics memory, run the model and search entirely on the GPU.
- As an experiment, cache-augmented generation (CAG): load the whole knowledge base,
  about 37,000 tokens, into the model's context once and reuse it for every
  question, so no search step can miss a passage such as Tradirend's. Worth testing
  only if memory, the size of the knowledge base and the structure of its pages
  allow.
- With Lime Green's own enquiries, fine-tune the embedding model and reranker on
  customers' wording, fine-tune a small model on verified answers for lighter
  machines, add the PDF data sheets, and have the technical team grade a test set.

## How this was built

Claude and Codex were used as paired coding and review tools. I set the scope
and made the final decisions. One tool implemented each stage and the other
reviewed it independently; the roles changed between tasks.

For the frozen evaluation, the expected answers were written and locked before the
engine was built and were not opened until all 270 answers had been saved; both
tools then graded every answer without knowing which model wrote it, and I settled
their disagreements and applied the locked forbidden-answer rules. For the held-out
comparison, new chats that had never seen the project judged the answers in pairs,
with Gemini breaking their disagreements. This grading was offline and is not part
of the running assistant.

The independent reviews led to concrete corrections in passage scoring, safety
wording, incomplete model replies and reranker response validation.

## Licence

MIT; see `LICENSE`.

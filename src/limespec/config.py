"""Every fixed setting in one place: paths, model servers, retrieval and generation.

Paths are relative to the repository root, where every command is run.
"""

import os
from pathlib import Path

SITE = "https://www.lime-green.co.uk/"
SOURCES_FILE = Path("sources.txt")
PAGE_CACHE = Path("data/site")  # fetched HTML; never committed
# The site's documents and images, each stored once by SHA-256 with manifest.json;
# never committed.
FILE_STORE = Path("data/files")
# Each stored PDF read into elements (limespec.documents); never committed.
READINGS = Path("data/elements")
# LibreOffice, unpacked into tools/ (never committed), lays out Word files (X43).
LIBREOFFICE = Path(
    os.environ.get("LIMESPEC_LIBREOFFICE", "tools/libreoffice/program/soffice.exe")
)
# Openly licensed external documents to collect: URL, then licence, per line.
EXTERNAL_SOURCES = Path("sources-external.txt")
# The Postgres index (deploy/compose.yaml). It holds a password, so it comes from the
# environment: copy .env.example to .env and run `uv run --env-file .env ...`.
DATABASE_URL = os.environ.get("LIMESPEC_DATABASE_URL", "")
# The database is on this machine; psycopg's own default waits 130 s before failing.
DATABASE_CONNECT_TIMEOUT_SECONDS = 5
# An index version to serve in place of the live one, so a candidate can be evaluated
# before it goes live. Unset, the live version is served.
INDEX_VERSION = os.environ.get("LIMESPEC_INDEX_VERSION", "")

USER_AGENT = "lime-green-assistant/0.1 (technical interview exercise)"
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0
REQUEST_RETRIES = 2

# Qwen3-Embedding-4B on the CPU, its vectors cut to the index's size (E5, D104). An
# index version built with another embedder is served with that one: set both variables
# (the 0.6B model: http://127.0.0.1:8081/v1/embeddings, Qwen3-Embedding-0.6B-f16.gguf).
EMBEDDING_URL = os.environ.get(
    "LIMESPEC_EMBEDDING_URL", "http://127.0.0.1:8084/v1/embeddings"
)
EMBEDDING_MODEL = os.environ.get(
    "LIMESPEC_EMBEDDING_MODEL", "Qwen3-Embedding-4B-Q8_0.gguf (first 1024)"
)
EMBEDDING_BATCH_SIZE = 16
# The index column's size. A model trained for shorter vectors (Qwen3-Embedding's
# Matryoshka training) gives longer ones that are cut to this size and normalised.
EMBEDDING_DIMENSIONS = 1024
# Qwen3-Embedding expects an instruction before a query and nothing before a passage.
QUERY_INSTRUCTION = (
    "Instruct: Given a question about Lime Green building products, "
    "retrieve the website passages that answer it\nQuery: "
)

RERANK_URL = "http://127.0.0.1:8082/v1/rerank"
# The model servers' key (llama-server --api-key), a secret, so it comes from the
# environment (.env). Without it no key is sent.
MODEL_API_KEY = os.environ.get("LIMESPEC_MODEL_API_KEY", "")
SEARCH_TIMEOUT_SECONDS = 120.0  # embedding or reranking one request

# Longer sections split between paragraphs, and a long paragraph at sentence ends;
# passages do not overlap.
MAX_PASSAGE_CHARS = 1500
CANDIDATES_PER_METHOD = 20  # keyword and vector candidates before fusion
RRF_K = 60  # the standard reciprocal-rank-fusion constant
# The reranker orders the best fused candidates and the model gets its top 8.
# Both settings were measured on practice questions, never tuned on the frozen
# evaluation set.
RERANK_CANDIDATES = 20
TOP_K = 8

# The generator. A candidate generator served elsewhere is evaluated by pointing the
# whole answer path at it (E8).
CHAT_URL = os.environ.get(
    "LIMESPEC_CHAT_URL", "http://127.0.0.1:8080/v1/chat/completions"
)
# Qwen keeps its expert layers in system RAM, so an answer can take a while.
CHAT_TIMEOUT_SECONDS = 300.0
# Deterministic sampling, so the same question gets a repeatable answer.
TEMPERATURE = 0.0
SEED = 42
MAX_ANSWER_TOKENS = 2048
# Bounds on the answer, so a model that starts repeating itself stops well inside
# the token limit instead of being cut off mid-JSON.
MAX_CLAIMS = 8
# A question is searched as at most MAX_PARTS separate things; a question with
# several gets up to MAX_PASSAGES passages, interleaved from each search (S2b C2,
# within X39's budget of 32).
MAX_PARTS = 6
MAX_PASSAGES = 12
# After each search, a search inside the products its query names adds its best
# SCOPED_TOP passages (E5 B4), all passages given staying within PASSAGE_BUDGET
# (X39: evidence use falls beyond it).
SCOPED_TOP = 4
PASSAGE_BUDGET = 32
MAX_QUOTES_PER_CLAIM = 3
CLOSEST_PAGES = 3  # pages listed with the insufficient-evidence text

# `limespec serve` listens on this machine only: the page is a local demo. 8090
# sits beside the model servers (8080 chat, 8081 embeddings, 8082 reranking) and
# avoids 8000, which other development servers often hold; `serve --port` picks
# another.
APP_HOST = "127.0.0.1"
APP_PORT = 8090
# The API refuses longer questions (OWASP LLM10, unbounded consumption). The longest
# question in the evaluation sets is 237 characters.
MAX_QUESTION_CHARS = 1000
# /readyz asks each model server's /health; a loaded server answers at once.
HEALTH_TIMEOUT_SECONDS = 2.0

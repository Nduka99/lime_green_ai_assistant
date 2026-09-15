"""Every fixed setting in one place: paths, model servers, retrieval and generation.

Paths are relative to the repository root, where every command is run.
"""

from pathlib import Path

SITE = "https://www.lime-green.co.uk/"
SOURCES_FILE = Path("sources.txt")
PAGE_CACHE = Path("data/site")  # fetched HTML; never committed
DATABASE = Path("data/limespec.db")  # the local index; never committed

USER_AGENT = "lime-green-assistant/0.1 (technical interview exercise)"
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0
REQUEST_RETRIES = 2

EMBEDDING_URL = "http://127.0.0.1:8081/v1/embeddings"
EMBEDDING_MODEL = "Qwen3-Embedding-0.6B-f16.gguf"
EMBEDDING_BATCH_SIZE = 16
# Qwen3-Embedding expects an instruction before a query and nothing before a passage.
QUERY_INSTRUCTION = (
    "Instruct: Given a question about Lime Green building products, "
    "retrieve the website passages that answer it\nQuery: "
)

RERANK_URL = "http://127.0.0.1:8082/v1/rerank"
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

CHAT_URL = "http://127.0.0.1:8080/v1/chat/completions"
# Qwen keeps its expert layers in system RAM, so an answer can take a while.
CHAT_TIMEOUT_SECONDS = 300.0
# Deterministic sampling, so the same question gets a repeatable answer.
TEMPERATURE = 0.0
SEED = 42
MAX_ANSWER_TOKENS = 2048
# Bounds on the answer, so a model that starts repeating itself stops well inside
# the token limit instead of being cut off mid-JSON.
MAX_CLAIMS = 8
MAX_QUOTES_PER_CLAIM = 3
CLOSEST_PAGES = 3  # pages listed with the insufficient-evidence text

# `limespec serve` listens on this machine only: the page is a local demo. 8090
# sits beside the model servers (8080 chat, 8081 embeddings, 8082 reranking) and
# avoids 8000, which other development servers often hold; `serve --port` picks
# another.
APP_HOST = "127.0.0.1"
APP_PORT = 8090

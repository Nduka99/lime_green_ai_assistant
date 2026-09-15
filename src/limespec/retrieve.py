"""Find the passages that best match a question.

Two independent rankings are merged by reciprocal-rank fusion (RRF):
keyword search (SQLite FTS5, BM25) finds exact terms such as product names,
and vector search (cosine similarity of embeddings) finds paraphrases. A
cross-encoder reranker then reads the question with each of the best fused
candidates and orders them, so the passages the model sees first are the most
relevant ones.
"""

import math
import re
import sqlite3
from array import array
from collections.abc import Callable, Sequence

from limespec import config
from limespec.models import Passage

Embed = Callable[[list[str]], list[list[float]]]
# One relevance score per document for a query, in the documents' order.
Rerank = Callable[[str, list[str]], list[float]]


def unit_vector(vector: Sequence[float]) -> list[float]:
    """Scale to length 1, so cosine similarity becomes a plain dot product."""
    length = math.sqrt(sum(x * x for x in vector))
    return [x / length for x in vector] if length else list(vector)


def to_blob(vector: Sequence[float]) -> bytes:
    """Store a vector as normalised 32-bit floats."""
    return array("f", unit_vector(vector)).tobytes()


def from_blob(blob: bytes) -> array[float]:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def keyword_ranking(conn: sqlite3.Connection, question: str, limit: int) -> list[int]:
    """Passage ids ranked by BM25 over the question's words."""
    words = re.findall(r"\w+", question.lower())
    if not words:
        return []
    # Quoting each word keeps FTS5 from reading AND, OR, NOT or punctuation as syntax.
    query = " OR ".join(f'"{word}"' for word in words)
    rows = conn.execute(
        "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? "
        "ORDER BY bm25(passages_fts) LIMIT ?",
        (query, limit),
    )
    return [row[0] for row in rows]


def vector_ranking(
    conn: sqlite3.Connection, query_vector: Sequence[float], limit: int
) -> list[int]:
    """Passage ids ranked by cosine similarity to the query vector."""
    query = unit_vector(query_vector)
    scored = [
        (-sum(q * v for q, v in zip(query, from_blob(blob), strict=True)), passage_id)
        for passage_id, blob in conn.execute("SELECT id, embedding FROM passages")
    ]
    return [passage_id for _, passage_id in sorted(scored)[:limit]]


def fuse(rankings: Sequence[list[int]], k: int = config.RRF_K) -> list[int]:
    """Reciprocal-rank fusion: each ranking adds 1 / (k + rank) to a passage.

    Ties are broken by passage id, so the result is deterministic.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, passage_id in enumerate(ranking, start=1):
            scores[passage_id] = scores.get(passage_id, 0.0) + 1 / (k + rank)
    return sorted(scores, key=lambda passage_id: (-scores[passage_id], passage_id))


def load_passage(conn: sqlite3.Connection, passage_id: int) -> Passage:
    row = conn.execute(
        "SELECT passages.id, passages.url, pages.title, passages.heading, "
        "passages.text, pages.fetched_at "
        "FROM passages JOIN pages ON pages.url = passages.url WHERE passages.id = ?",
        (passage_id,),
    ).fetchone()
    return Passage(*row)


def search(
    conn: sqlite3.Connection, question: str, embed: Embed, rerank: Rerank
) -> list[Passage]:
    """The top passages for a question, best first."""
    query_vector = embed([config.QUERY_INSTRUCTION + question])[0]
    limit = config.CANDIDATES_PER_METHOD
    ranking = fuse(
        [
            keyword_ranking(conn, question, limit),
            vector_ranking(conn, query_vector, limit),
        ]
    )
    candidates = [
        load_passage(conn, passage_id)
        for passage_id in ranking[: config.RERANK_CANDIDATES]
    ]
    if not candidates:
        return []
    # The title tells the reranker which product a short passage is about.
    scores = rerank(question, [f"{p.title}\n{p.text}" for p in candidates])
    # A stable sort keeps the fused order among equal scores, so ties are deterministic.
    order = sorted(range(len(candidates)), key=lambda i: -scores[i])
    return [candidates[i] for i in order[: config.TOP_K]]

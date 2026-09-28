"""The Postgres index: write an index version, choose which version is live, and
rank its passages for a question: keywords by BM25 (pg_textsearch), meaning by
pgvector. Experiment X2 showed this ranks as well as the SQLite index did.

All SQL lives here. Retrieval and answering stay plain functions that receive the
rankings, as they did with SQLite. An index version is written beside the live one
and made live in one transaction, so a failed build never touches what is served.
"""

import re
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from limespec import config, prices
from limespec.models import Passage
from limespec.retrieve import Embed, Rerank, fuse, rerank_top, unit_vector

Connection = psycopg.Connection[tuple[Any, ...]]
PageRow = tuple[str, str, str, str]  # url, title, fetched_at (ISO 8601), sha256
PassageRow = tuple[str, str, str, str]  # url, title, heading, text

# English stemming that keeps stop words (migration 20260928100000). pg_textsearch
# finds a custom configuration only by its schema-qualified name.
KEYWORD_CONFIG = "public.english_keep_stop"
# What keyword search reads: the page title and the passage text, as SQLite did.
KEYWORD_TEXT = sql.SQL("(title || ' ' || text)")


def bm25_index(version_id: int) -> str:
    """Each version's own BM25 index, so its word statistics cover that version."""
    return f"passages_bm25_v{version_id}"


def vector_text(vector: Sequence[float]) -> str:
    """pgvector's text form, "[x,y,...]", of the unit-length vector.

    Passing vectors as text keeps the code free of an adapter package; Postgres
    parses it with a ::vector cast.
    """
    return "[" + ",".join(repr(float(x)) for x in unit_vector(vector)) + "]"


def write_version(
    conn: Connection,
    pages: Sequence[PageRow],
    passages: Sequence[PassageRow],
    vectors: Sequence[Sequence[float]],
    manifest: dict[str, str],
) -> int:
    """Store one index version (not yet live) with its BM25 index; return its id.

    A page captured with the same bytes before is reused, not stored twice.
    """
    with conn.transaction():
        document_ids = {}
        for url, title, fetched_at, sha256 in pages:
            row = conn.execute(
                "INSERT INTO documents (url, title, fetched_at, sha256) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (url, sha256) DO UPDATE SET title = EXCLUDED.title "
                "RETURNING id",
                (url, title, fetched_at, sha256),
            ).fetchone()
            assert row is not None  # RETURNING always yields the row
            document_ids[url] = row[0]
        version = conn.execute(
            "INSERT INTO index_versions "
            "(corpus_sha256, passages_sha256, embedding_model) "
            "VALUES (%s, %s, %s) RETURNING id",
            (
                manifest["corpus_sha256"],
                manifest["passages_sha256"],
                manifest["embedding_model"],
            ),
        ).fetchone()
        assert version is not None
        rows = []
        for (url, title, heading, text), vector in zip(passages, vectors, strict=True):
            document_id = document_ids[url]
            # A passage with a price is kept for audit but never searched (X16).
            commercial = prices.states_price(text)
            rows.append(
                (
                    version[0],
                    document_id,
                    title,
                    heading,
                    text,
                    vector_text(vector),
                    commercial,
                )
            )
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO passages (index_version_id, document_id, title, heading, "
                "text, embedding, commercial) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector, %s)",
                rows,
            )
        # A partial index keeps its own word statistics. The version id is a
        # literal, because the planner must see the predicate to use the index.
        conn.execute(
            sql.SQL(
                "CREATE INDEX {} ON passages USING bm25 ({}) "
                "WITH (text_config = {}) WHERE index_version_id = {}"
            ).format(
                sql.Identifier(bm25_index(version[0])),
                KEYWORD_TEXT,
                sql.Literal(KEYWORD_CONFIG),
                sql.Literal(version[0]),
            )
        )
    return int(version[0])


def delete_version(conn: Connection, version_id: int) -> None:
    """Remove a version that is not live: its passages and its BM25 index."""
    with conn.transaction():
        deleted = conn.execute(
            "DELETE FROM index_versions WHERE id = %s AND NOT live", (version_id,)
        )
        if deleted.rowcount != 1:
            raise ValueError(f"no index version {version_id} that is not live")
        conn.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(bm25_index(version_id))
            )
        )


def set_live(conn: Connection, version_id: int) -> None:
    """Make this version the one that is served, in a single transaction."""
    with conn.transaction():
        conn.execute("UPDATE index_versions SET live = false WHERE live")
        updated = conn.execute(
            "UPDATE index_versions SET live = true WHERE id = %s", (version_id,)
        )
        if updated.rowcount != 1:
            raise ValueError(f"no index version {version_id}")


def live_version(conn: Connection) -> tuple[int, str] | None:
    """The live version's id and embedding model, or None before the first build."""
    row = conn.execute(
        "SELECT id, embedding_model FROM index_versions WHERE live"
    ).fetchone()
    return (int(row[0]), str(row[1])) if row else None


def index_version(conn: Connection, version_id: int) -> tuple[int, str] | None:
    """One version's id and embedding model, or None if there is no such version."""
    row = conn.execute(
        "SELECT id, embedding_model FROM index_versions WHERE id = %s", (version_id,)
    ).fetchone()
    return (int(row[0]), str(row[1])) if row else None


def keyword_ranking(
    conn: Connection, version_id: int, question: str, limit: int
) -> list[int]:
    """Passage ids ranked by BM25 over the question's words (experiment X2).

    Passages that share no word with the question score 0 and are left out, as a
    full-text match leaves them out, and so are passages with a price (X16). Ties
    keep passage id order.
    """
    if not re.search(r"\w", question):
        return []
    score = sql.SQL("{} <@> to_bm25query({}, {})").format(
        KEYWORD_TEXT, sql.Literal(question), sql.Literal(bm25_index(version_id))
    )
    rows = conn.execute(
        sql.SQL(
            "SELECT id FROM passages WHERE index_version_id = {} AND {} < 0 "
            "AND NOT commercial ORDER BY {}, id LIMIT {}"
        ).format(sql.Literal(version_id), score, score, sql.Literal(limit))
    ).fetchall()
    return [row[0] for row in rows]


def vector_ranking(
    conn: Connection, version_id: int, query_vector: Sequence[float], limit: int
) -> list[int]:
    """Passage ids ranked by cosine similarity (inner product of unit vectors),
    leaving out passages with a price (X16)."""
    rows = conn.execute(
        "SELECT id FROM passages WHERE index_version_id = %s AND NOT commercial "
        "ORDER BY embedding <#> %s::vector, id LIMIT %s",
        (version_id, vector_text(query_vector), limit),
    ).fetchall()
    return [row[0] for row in rows]


def search(
    conn: Connection, version_id: int, question: str, embed: Embed, rerank: Rerank
) -> list[Passage]:
    """The top passages of one index version for a question, best first.

    Keyword and vector rankings, fused, then the reranker orders the best
    candidates (`retrieve.rerank_top`).
    """
    query_vector = embed([config.QUERY_INSTRUCTION + question])[0]
    limit = config.CANDIDATES_PER_METHOD
    ranking = fuse(
        [
            keyword_ranking(conn, version_id, question, limit),
            vector_ranking(conn, version_id, query_vector, limit),
        ]
    )
    candidates = load_passages(conn, ranking[: config.RERANK_CANDIDATES])
    return rerank_top(question, candidates, rerank)


def record_answer(
    conn: Connection,
    question: str,
    status: str,
    shown: dict[str, Any],
    removed: list[dict[str, str]],
    passage_ids: Sequence[int],
    index_version_id: int,
    embedding_model: str,
    prompt_sha256: str,
    seconds: float,
) -> int:
    """Store one answer's audit record (plain, JSON-compatible data); return its id."""
    row = conn.execute(
        "INSERT INTO answers (question, status, shown, removed, passage_ids, "
        "index_version_id, embedding_model, prompt_sha256, seconds) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            question,
            status,
            Jsonb(shown),
            Jsonb(removed),
            list(passage_ids),
            index_version_id,
            embedding_model,
            prompt_sha256,
            seconds,
        ),
    ).fetchone()
    assert row is not None  # RETURNING always yields the row
    conn.commit()
    return int(row[0])


def load_passages(conn: Connection, passage_ids: Sequence[int]) -> list[Passage]:
    """The passages with these ids, in the order given."""
    rows = conn.execute(
        "SELECT passages.id, documents.url, passages.title, passages.heading, "
        "passages.text, documents.fetched_at "
        "FROM passages JOIN documents ON documents.id = passages.document_id "
        "WHERE passages.id = ANY(%s)",
        (list(passage_ids),),
    ).fetchall()
    by_id = {}
    for passage_id, url, title, heading, text, fetched_at in rows:
        captured = fetched_at.astimezone(UTC).isoformat(timespec="seconds")
        by_id[passage_id] = Passage(passage_id, url, title, heading, text, captured)
    return [by_id[passage_id] for passage_id in passage_ids]

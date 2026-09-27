"""The Postgres index: write an index version, choose which version is live, and
rank its passages for a question.

All SQL lives here. Retrieval and answering stay plain functions that receive the
rankings, as they did with SQLite. An index version is written beside the live one
and made live in one transaction, so a failed build never touches what is served.
"""

import re
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import psycopg

from limespec.models import Passage
from limespec.retrieve import unit_vector

Connection = psycopg.Connection[tuple[Any, ...]]
PageRow = tuple[str, str, str, str]  # url, title, fetched_at (ISO 8601), sha256
PassageRow = tuple[str, str, str, str]  # url, title, heading, text


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
    """Store one index version (not yet live) and return its id.

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
            rows.append(
                (version[0], document_id, title, heading, text, vector_text(vector))
            )
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO passages "
                "(index_version_id, document_id, title, heading, text, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                rows,
            )
    return int(version[0])


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


def keyword_ranking(
    conn: Connection, version_id: int, question: str, limit: int
) -> list[int]:
    """Passage ids ranked by full-text match on any of the question's words.

    Words are joined with OR, as the SQLite search did; Postgres stems them and
    drops stop words. Ties keep passage id order, so the result is deterministic.
    """
    words = re.findall(r"\w+", question.lower())
    if not words:
        return []
    rows = conn.execute(
        "SELECT id FROM passages, to_tsquery('english', %s) AS query "
        "WHERE index_version_id = %s AND search @@ query "
        "ORDER BY ts_rank(search, query) DESC, id LIMIT %s",
        (" | ".join(words), version_id, limit),
    ).fetchall()
    return [row[0] for row in rows]


def vector_ranking(
    conn: Connection, version_id: int, query_vector: Sequence[float], limit: int
) -> list[int]:
    """Passage ids ranked by cosine similarity (inner product of unit vectors)."""
    rows = conn.execute(
        "SELECT id FROM passages WHERE index_version_id = %s "
        "ORDER BY embedding <#> %s::vector, id LIMIT %s",
        (version_id, vector_text(query_vector), limit),
    ).fetchall()
    return [row[0] for row in rows]


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

"""The Postgres index: write an index version, choose which version is live, and
rank its passages for a question: keywords by BM25 (pg_textsearch), meaning by
pgvector. Experiment X2 showed this ranks as well as the SQLite index did.

All SQL lives here. Retrieval and answering stay plain functions that receive the
rankings, as they did with SQLite. An index version is written beside the live one
and made live in one transaction, so a failed build never touches what is served.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from limespec import config, prices
from limespec.models import Passage
from limespec.retrieve import Embed, Rerank, fuse, rerank_top, unit_vector
from limespec.scope import SEPARATOR

Connection = psycopg.Connection[tuple[Any, ...]]
PageRow = tuple[str, str, str, str]  # url, title, fetched_at (ISO 8601), sha256
# url, title, heading, text, context, page (None for a web page)
PassageRow = tuple[str, str, str, str, str, int | None]

# English stemming that keeps stop words (migration 20260928100000). pg_textsearch
# finds a custom configuration only by its schema-qualified name.
KEYWORD_CONFIG = "public.english_keep_stop"
# What keyword search reads: the title, the context (empty for web passages, X9) and
# the text. pg_textsearch scores it with the named version's index, so versions
# built before the context existed rank exactly as before.
KEYWORD_TEXT = sql.SQL("(title || ' ' || context || ' ' || text)")


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
    images: Sequence[str] = (),
    pictures: Mapping[str, bytes] | None = None,
    picture_vectors: Mapping[str, Sequence[float]] | None = None,
) -> int:
    """Store one index version (not yet live) with its BM25 index; return its id.

    A page captured with the same bytes before is reused, not stored twice. `images`
    names each passage's picture ("" for none), in passage order; `pictures` holds the
    PNG of each, stored once across versions, and `picture_vectors` their SigLIP2
    vectors. Each passage's search channel follows from what it is (`channel`).
    """
    images = images or [""] * len(passages)
    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO images (id, png) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                list((pictures or {}).items()),
            )
            cursor.executemany(
                "UPDATE images SET siglip = %s::vector WHERE id = %s",
                [
                    (vector_text(vector), identity)
                    for identity, vector in (picture_vectors or {}).items()
                ],
            )
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
        for passage, vector, image in zip(passages, vectors, images, strict=True):
            url, title, heading, text, context, page = passage
            # A passage with a price is kept for audit but never searched (X16).
            commercial = prices.states_price(text)
            rows.append(
                (
                    version[0],
                    document_ids[url],
                    title,
                    heading,
                    text,
                    context,
                    page,
                    vector_text(vector),
                    commercial,
                    image or None,
                    channel(title, image),
                )
            )
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO passages (index_version_id, document_id, title, heading, "
                "text, context, page, embedding, commercial, image, channel) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)",
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


def channel(title: str, image: str) -> str:
    """A passage's search channel (X44 F2): a picture's, general guidance (an external
    document, titled with its publisher first), or the company's own content."""
    if image:
        return "picture"
    return "guidance" if title.startswith(config.GUIDANCE_TITLE) else "company"


def known_vectors(
    conn: Connection, embedding_model: str
) -> dict[tuple[str, str, str], list[float]]:
    """The newest version embedded by `embedding_model`: each passage's (title,
    context, text) and its stored vector, so a new build embeds only new text."""
    row = conn.execute(
        "SELECT max(id) FROM index_versions WHERE embedding_model = %s",
        (embedding_model,),
    ).fetchone()
    if row is None or row[0] is None:
        return {}
    found = {}
    for title, context, text, vector in conn.execute(
        "SELECT title, context, text, embedding::text FROM passages "
        "WHERE index_version_id = %s",
        (row[0],),
    ):
        found[(title, context, text)] = [
            float(x) for x in vector.strip("[]").split(",")
        ]
    return found


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


def in_scope(scope: Sequence[str]) -> sql.Composable:
    """A filter keeping passages whose scope (`scope.scope_of` their title) is one of
    `scope`; no filter when it is empty."""
    if not scope:
        return sql.SQL("")
    return sql.SQL(" AND split_part(title, {}, 1) = ANY({})").format(
        sql.Literal(SEPARATOR), sql.Literal(list(scope))
    )


def in_channel(name: str) -> sql.Composable:
    """A filter keeping one search channel's passages (X44 F2). A picture is searched
    by words only when it has words of its own: text, or a context line after its
    section path (`images.picture_passages`)."""
    found = sql.SQL(" AND channel = {}").format(sql.Literal(name))
    if name == "picture":
        found += sql.SQL(" AND (text <> '' OR strpos(context, chr(10)) > 0)")
    return found


def keyword_ranking(
    conn: Connection,
    version_id: int,
    question: str,
    limit: int,
    scope: Sequence[str] = (),
    channel: str = "company",
) -> list[int]:
    """Passage ids of one channel ranked by BM25 over the question's words (X2).

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
            "AND NOT commercial{}{} ORDER BY {}, id LIMIT {}"
        ).format(
            sql.Literal(version_id),
            score,
            in_scope(scope),
            in_channel(channel),
            score,
            sql.Literal(limit),
        )
    ).fetchall()
    return [row[0] for row in rows]


def vector_ranking(
    conn: Connection,
    version_id: int,
    query_vector: Sequence[float],
    limit: int,
    scope: Sequence[str] = (),
    channel: str = "company",
) -> list[int]:
    """Passage ids of one channel ranked by cosine similarity (inner product of unit
    vectors), leaving out passages with a price (X16)."""
    query = sql.SQL(
        "SELECT id FROM passages WHERE index_version_id = %s AND NOT commercial{}{} "
        "ORDER BY embedding <#> %s::vector, id LIMIT %s"
    ).format(in_scope(scope), in_channel(channel))
    rows = conn.execute(
        query, (version_id, vector_text(query_vector), limit)
    ).fetchall()
    return [row[0] for row in rows]


def search(
    conn: Connection,
    version_id: int,
    question: str,
    embed: Embed,
    rerank: Rerank,
    top: int | None = None,
    scope: Sequence[str] = (),
    also: Sequence[list[int]] = (),
    channel: str = "company",
) -> list[Passage]:
    """The top passages of one index version's channel for a question, best first:
    `top` of them, or `config.TOP_K`; only passages of the named `scope`, if one is
    given. The fused rankings' best candidates ordered by the reranker
    (`retrieve.rerank_top`)."""
    ranking = fused(conn, version_id, question, embed, scope, also, channel)
    candidates = load_passages(conn, ranking[: config.RERANK_CANDIDATES])
    return rerank_top(question, candidates, rerank, top)


def fused(
    conn: Connection,
    version_id: int,
    question: str,
    embed: Embed,
    scope: Sequence[str] = (),
    also: Sequence[list[int]] = (),
    channel: str = "company",
) -> list[int]:
    """One channel's keyword and vector rankings for a question, and any rankings
    `also` given (passage ids, best first), fused: passage ids, best first."""
    query_vector = embed([config.QUERY_INSTRUCTION + question])[0]
    limit = config.CANDIDATES_PER_METHOD
    return fuse(
        [
            keyword_ranking(conn, version_id, question, limit, scope, channel),
            vector_ranking(conn, version_id, query_vector, limit, scope, channel),
            *also,
        ]
    )


def picture_ranking(
    conn: Connection, version_id: int, query_vector: Sequence[float], limit: int
) -> list[int]:
    """Picture passage ids ranked by what their pictures show: SigLIP2's cosine
    between the question and each stored picture (X44 F2)."""
    rows = conn.execute(
        "SELECT p.id FROM passages p JOIN images i ON i.id = p.image "
        "WHERE p.index_version_id = %s AND p.channel = 'picture' "
        "AND i.siglip IS NOT NULL ORDER BY i.siglip <#> %s::vector, p.id LIMIT %s",
        (version_id, vector_text(query_vector), limit),
    ).fetchall()
    return [row[0] for row in rows]


def product_names(conn: Connection, version_id: int) -> list[str]:
    """The titles of the version's product pages: the scopes a question can name."""
    rows = conn.execute(
        "SELECT DISTINCT p.title FROM passages p "
        "JOIN documents d ON d.id = p.document_id "
        "WHERE p.index_version_id = %s AND d.url LIKE %s AND d.url NOT ILIKE %s "
        "ORDER BY p.title",
        (version_id, config.SITE + "products/%", "%.pdf"),
    ).fetchall()
    return [row[0] for row in rows]


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
        "passages.text, documents.fetched_at, passages.page, passages.context, "
        "coalesce(passages.image, '') "
        "FROM passages JOIN documents ON documents.id = passages.document_id "
        "WHERE passages.id = ANY(%s)",
        (list(passage_ids),),
    ).fetchall()
    by_id = {}
    for passage_id, url, title, heading, text, fetched_at, page, context, image in rows:
        captured = fetched_at.astimezone(UTC).isoformat(timespec="seconds")
        by_id[passage_id] = Passage(
            passage_id, url, title, heading, text, captured, page, context, image
        )
    return [by_id[passage_id] for passage_id in passage_ids]


def given_passages(conn: Connection, answer_id: int) -> tuple[int, list[Passage]]:
    """The index version an answer used and the passages its model was given, in the
    order given (read from the answer's audit record)."""
    row = conn.execute(
        "SELECT index_version_id, passage_ids FROM answers WHERE id = %s", (answer_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no answer record {answer_id}")
    return int(row[0]), load_passages(conn, row[1])


def removed_claims(conn: Connection, answer_id: int) -> list[dict[str, str]]:
    """The claims an answer's checks removed, each with its reason (read from the
    answer's audit record)."""
    row = conn.execute(
        "SELECT removed FROM answers WHERE id = %s", (answer_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no answer record {answer_id}")
    return list(row[0])


def document_passages(conn: Connection, version_id: int, url: str) -> list[Passage]:
    """Every passage of one document in an index version, in stored order."""
    rows = conn.execute(
        "SELECT passages.id FROM passages "
        "JOIN documents ON documents.id = passages.document_id "
        "WHERE passages.index_version_id = %s AND documents.url = %s "
        "ORDER BY passages.id",
        (version_id, url),
    ).fetchall()
    return load_passages(conn, [row[0] for row in rows])


def passage_count(conn: Connection, version_id: int) -> int:
    """How many passages an index version holds."""
    row = conn.execute(
        "SELECT count(*) FROM passages WHERE index_version_id = %s", (version_id,)
    ).fetchone()
    assert row is not None  # count(*) always yields a row
    return int(row[0])


def picture_passages(conn: Connection, version_id: int) -> dict[str, int]:
    """The passage each picture of an index version became, by picture id (not those
    with a price, X16)."""
    rows = conn.execute(
        "SELECT image, id FROM passages WHERE index_version_id = %s "
        "AND image IS NOT NULL AND NOT commercial ORDER BY id",
        (version_id,),
    ).fetchall()
    return {image: passage_id for image, passage_id in rows}


def searchable_passages(conn: Connection, version_id: int) -> list[Passage]:
    """Every passage search can return in an index version (not those with a price,
    X16), in stored order."""
    rows = conn.execute(
        "SELECT id FROM passages WHERE index_version_id = %s AND NOT commercial "
        "ORDER BY id",
        (version_id,),
    ).fetchall()
    return load_passages(conn, [row[0] for row in rows])


def searchable_texts(conn: Connection, version_id: int) -> list[str]:
    """The text of every passage search can return in an index version (not those
    with a price, X16)."""
    rows = conn.execute(
        "SELECT text FROM passages WHERE index_version_id = %s AND NOT commercial "
        "ORDER BY id",
        (version_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def picture(conn: Connection, image_id: str) -> bytes | None:
    """A stored picture's PNG, or None."""
    row = conn.execute("SELECT png FROM images WHERE id = %s", (image_id,)).fetchone()
    return bytes(row[0]) if row else None

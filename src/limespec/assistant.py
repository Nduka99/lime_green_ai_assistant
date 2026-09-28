"""The one call behind every interface: a question answered from the index
(Postgres when configured, otherwise the local SQLite file).

The command line and the web page both call `ask`, so they cannot differ in what
they retrieve, which model requests they make or what they verify.
"""

import sqlite3
from contextlib import closing

import psycopg

from limespec import config, llm, store
from limespec.answer import answer
from limespec.ingest import IngestError
from limespec.models import Answer
from limespec.retrieve import search


def open_index() -> sqlite3.Connection:
    """The local index, or a clear error if `limespec ingest` has not been run."""
    if not config.DATABASE.exists():
        raise IngestError(f"no index at {config.DATABASE}; run `limespec ingest` first")
    try:
        conn = sqlite3.connect(config.DATABASE)
        # A damaged file often opens but fails on its first query, so query it now
        # and close the connection before reporting the error.
        try:
            conn.execute(
                "SELECT passages.id, passages.url, pages.title, passages.heading, "
                "passages.text, pages.fetched_at, passages.embedding "
                "FROM passages JOIN pages ON pages.url = passages.url LIMIT 1"
            ).fetchone()
            conn.execute("SELECT rowid FROM passages_fts LIMIT 1").fetchone()
        except sqlite3.Error:
            conn.close()
            raise
    except sqlite3.Error as error:
        raise IngestError(
            f"cannot read index at {config.DATABASE}; "
            "run `limespec ingest` to rebuild it"
        ) from error
    return conn


def ask(question: str) -> Answer:
    """Answer one question with the configured llama.cpp servers and the index:
    the live Postgres index when LIMESPEC_DATABASE_URL is set, else SQLite."""
    if config.DATABASE_URL:
        return ask_postgres(question)
    with closing(open_index()) as conn:
        return answer(
            question, lambda query: search(conn, query, llm.embed, llm.rerank), llm.chat
        )


def ask_postgres(question: str) -> Answer:
    try:
        conn = psycopg.connect(
            config.DATABASE_URL, connect_timeout=config.DATABASE_CONNECT_TIMEOUT_SECONDS
        )
    except psycopg.OperationalError as error:
        raise IngestError(f"cannot reach the Postgres index: {error}") from error
    with conn:
        version_id = live_index(conn)
        return answer(
            question,
            lambda query: store.search(conn, version_id, query, llm.embed, llm.rerank),
            llm.chat,
        )


def live_index(conn: store.Connection) -> int:
    """The live index version, only if it was embedded with the configured model:
    question vectors from another model would not match its passage vectors."""
    live = store.live_version(conn)
    if live is None:
        raise IngestError(
            "no live Postgres index; run `uv run --env-file .env limespec ingest "
            "--postgres`"
        )
    version_id, embedding_model = live
    if embedding_model != config.EMBEDDING_MODEL:
        raise IngestError(
            f"the live index was embedded with {embedding_model}, but the configured "
            f"model is {config.EMBEDDING_MODEL}; rebuild it with `limespec ingest "
            "--postgres`"
        )
    return version_id

"""The one call behind every interface: a question answered from the local index.

The command line and the web page both call `ask`, so they cannot differ in what
they retrieve, which model requests they make or what they verify.
"""

import sqlite3
from contextlib import closing

from limespec import config, llm
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
    """Answer one question with the configured llama.cpp servers and the index."""
    with closing(open_index()) as conn:
        return answer(
            question, lambda query: search(conn, query, llm.embed, llm.rerank), llm.chat
        )

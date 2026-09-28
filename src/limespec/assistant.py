"""The one call behind every interface: a question answered from the live
Postgres index, and recorded for audit.

The command line and the web page both call `ask`, so they cannot differ in what
they retrieve, which model requests they make or what they verify.
"""

import time
from collections.abc import Callable
from typing import Any

import psycopg

from limespec import config, llm, store, telemetry
from limespec.answer import EXPOSURE_SCHEMA, PROMPT_SHA256, Chat, Retrieve, answer
from limespec.ingest import IngestError
from limespec.models import Answer, Passage
from limespec.view import view


def ask(question: str) -> Answer:
    """Answer one question with the configured llama.cpp servers and the live
    Postgres index; the answer is recorded for audit."""
    result, _ = ask_and_record(question)
    return result


def no_stage(stage: str) -> None:
    """The default stage report: nobody is listening."""


def with_stages(
    retrieve: Retrieve, chat: Chat, on_stage: Callable[[str], None]
) -> tuple[Retrieve, Chat]:
    """The same retrieval and model calls, reporting each stage as it starts and
    tracing it: understanding (the first model request), searching, answering and
    checking (verification runs once the answer request returns; its outcome is
    traced on the answer's span)."""

    def staged_retrieve(query: str) -> list[Passage]:
        on_stage("searching")
        with telemetry.span("searching"):
            return retrieve(query)

    def staged_chat(system: str, user: str, schema: dict[str, Any]) -> object:
        if schema is EXPOSURE_SCHEMA:
            on_stage("understanding")
            with telemetry.span("understanding"):
                return chat(system, user, schema)
        on_stage("answering")
        with telemetry.span("answering"):
            reply = chat(system, user, schema)
        on_stage("checking")
        return reply

    return staged_retrieve, staged_chat


def ask_and_record(
    question: str, on_stage: Callable[[str], None] = no_stage
) -> tuple[Answer, int]:
    """Answer from the live Postgres index and store the audit record; return the
    answer and the record's id. `on_stage` hears each stage as it starts."""
    with telemetry.span("answer"), connect() as conn:
        version_id = live_index(conn)
        started = time.perf_counter()
        retrieve, chat = with_stages(
            lambda query: store.search(conn, version_id, query, llm.embed, llm.rerank),
            llm.chat,
            on_stage,
        )
        result = answer(question, retrieve, chat)
        seconds = time.perf_counter() - started
        removed = [{"text": r.text, "reason": r.reason} for r in result.rejected]
        answer_id = store.record_answer(
            conn,
            question=question,
            status=result.status,
            shown=dict(view(result)),
            removed=removed,
            passage_ids=[p.id for p in result.passages],
            index_version_id=version_id,
            embedding_model=config.EMBEDDING_MODEL,
            prompt_sha256=PROMPT_SHA256,
            seconds=seconds,
        )
        telemetry.record_answer(result, answer_id, version_id, seconds)
    return result, answer_id


def connect() -> store.Connection:
    """A connection to the Postgres index, or a clear error saying what is wrong."""
    if not config.DATABASE_URL:
        raise IngestError(
            "LIMESPEC_DATABASE_URL is not set; copy .env.example to .env and run "
            "with `uv run --env-file .env limespec ...`"
        )
    try:
        return psycopg.connect(
            config.DATABASE_URL, connect_timeout=config.DATABASE_CONNECT_TIMEOUT_SECONDS
        )
    except psycopg.OperationalError as error:
        raise IngestError(f"cannot reach the Postgres index: {error}") from error


def database_ready() -> bool:
    """Whether answers can be served and recorded: Postgres is reachable and has a
    live index embedded with the configured model."""
    try:
        with connect() as conn:
            live_index(conn)
    except IngestError:
        return False
    return True


def live_index(conn: store.Connection) -> int:
    """The live index version, only if it was embedded with the configured model:
    question vectors from another model would not match its passage vectors."""
    live = store.live_version(conn)
    if live is None:
        raise IngestError(
            "no live Postgres index; run `uv run --env-file .env limespec ingest`"
        )
    version_id, embedding_model = live
    if embedding_model != config.EMBEDDING_MODEL:
        raise IngestError(
            f"the live index was embedded with {embedding_model}, but the configured "
            f"model is {config.EMBEDDING_MODEL}; rebuild it with `limespec ingest`"
        )
    return version_id

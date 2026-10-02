"""The one call behind every interface: a question answered from the live
Postgres index, and recorded for audit.

The command line and the web page both call `ask`, so they cannot differ in what
they retrieve, which model requests they make or what they verify.
"""

import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import psycopg

from limespec import config, llm, scope, siglip, store, telemetry
from limespec.answer import (
    PROMPT_SHA256,
    UNDERSTAND_SCHEMA,
    Chat,
    Extra,
    Retrieve,
    answer,
    with_extras,
)
from limespec.ingest import IngestError
from limespec.models import Answer, Passage
from limespec.retrieve import Embed, Rerank, rerank_top
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

    searched = False

    def staged_retrieve(query: str) -> list[Passage]:
        # A question with several parts is searched several times: one stage event.
        nonlocal searched
        if not searched:
            on_stage("searching")
            searched = True
        with telemetry.span("searching"):
            return retrieve(query)

    def staged_chat(system: str, user: str, schema: dict[str, Any]) -> object:
        if schema is UNDERSTAND_SCHEMA:
            on_stage("understanding")
            with telemetry.span("understanding"):
                return chat(system, user, schema)
        on_stage("answering")
        with telemetry.span("answering"):
            reply = chat(system, user, schema)
        on_stage("checking")
        return reply

    return staged_retrieve, staged_chat


# SigLIP2's text vectors are computed here while the search's other requests run.
PICTURE_WORK = ThreadPoolExecutor(max_workers=2)


@dataclass(frozen=True)
class Models:
    """One answer's model calls, each remembering its results: one answer searches
    the same query in several channels and several searches (X44 F2, X45 T1).
    `picture` starts a query's SigLIP2 vector in a thread and returns its future, so
    it is computed while the query is embedded (X45 T2). Made for each answer, so
    nothing is kept between answers."""

    embed: Embed
    rerank: Rerank
    picture: Callable[[str], "Future[list[float]]"]


def answer_models() -> Models:
    """Fresh `Models` for one answer, calling the configured model servers."""
    vectors: dict[str, list[float]] = {}
    scores: dict[tuple[str, str], float] = {}
    started: dict[str, Future[list[float]]] = {}

    def embed(texts: list[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if text not in vectors]
        if missing:
            vectors.update(zip(missing, llm.embed(missing), strict=True))
        return [vectors[text] for text in texts]

    def rerank(query: str, documents: list[str]) -> list[float]:
        missing = [d for d in dict.fromkeys(documents) if (query, d) not in scores]
        if missing:
            found = llm.rerank(query, missing)
            scores.update({(query, d): v for d, v in zip(missing, found, strict=True)})
        return [scores[(query, document)] for document in documents]

    def picture(query: str) -> Future[list[float]]:
        if query not in started:
            started[query] = PICTURE_WORK.submit(siglip.text_vector, query)
        return started[query]

    return Models(embed, rerank, picture)


def retriever(
    conn: store.Connection, version_id: int, models: Models | None = None
) -> Retrieve:
    """One search of an index version's company channel with the configured model
    servers. It returns its whole reranked pool; `answer.gather` takes the top 8, or
    interleaves several searches up to 12 (S2b C2). The evaluation replay uses the
    same function. With `models`, the query's picture vector starts first."""

    def retrieve(query: str) -> list[Passage]:
        embed: Embed = llm.embed if models is None else models.embed
        rerank: Rerank = llm.rerank if models is None else models.rerank
        if models is not None:
            models.picture(query)
        return store.search(
            conn, version_id, query, embed, rerank, config.RERANK_CANDIDATES
        )

    return retrieve


def scoped_retriever(
    conn: store.Connection, version_id: int, models: Models | None = None
) -> Retrieve:
    """A search of an index version inside the products a query names (E5 B4): its
    best `config.SCOPED_TOP` passages, or none when the query names no product.
    Answers use it after each search; `evaluation replay --scoped` measures it."""
    named = scope.naming(store.product_names(conn, version_id))

    def retrieve(query: str) -> list[Passage]:
        names = named(query)
        if not names:
            return []
        embed: Embed = llm.embed if models is None else models.embed
        rerank: Rerank = llm.rerank if models is None else models.rerank
        return store.search(
            conn, version_id, query, embed, rerank, config.SCOPED_TOP, names
        )

    return retrieve


def extras(
    conn: store.Connection, version_id: int, models: Models | None = None
) -> Extra:
    """What each search adds after the company's top places (X44 F2): its best
    pictures, then general guidance placed on merit (`guidance_above`). A version
    with no pictures never loads the picture model."""
    has_pictures = bool(store.picture_passages(conn, version_id))
    use = models or answer_models()

    def add(query: str, company: Sequence[Passage]) -> list[Passage]:
        found = best_pictures(conn, version_id, query, use) if has_pictures else []
        return [*found, *guidance_above(conn, version_id, query, company, use)]

    return add


def best_pictures(
    conn: store.Connection, version_id: int, query: str, models: Models
) -> list[Passage]:
    """A search's best pictures: its best `config.PICTURES_PER_SEARCH` by their own
    words, then its best by what they show (SigLIP2) not already among them. Each
    retriever keeps its own places, as UniDoc-Bench splits its results: fused into
    one ranking, a picture both rank moderately displaced each one's best (X44
    amendment 1)."""
    best = config.PICTURES_PER_SEARCH
    limit = config.CANDIDATES_PER_METHOD
    vector = models.picture(query)
    words = store.fused(conn, version_id, query, models.embed, channel="picture")
    shown = store.picture_ranking(conn, version_id, vector.result(), limit)
    return store.load_passages(
        conn, list(dict.fromkeys([*words[:best], *shown[:best]]))
    )


def guidance_above(
    conn: store.Connection,
    version_id: int,
    query: str,
    company: Sequence[Passage],
    models: Models,
) -> list[Passage]:
    """General guidance the reranker puts above the company's last place: its best
    candidates are reranked with the company's top places, and at most
    `config.GUIDANCE_PER_SEARCH` of those ahead of every company passage's last are
    kept. With no company passage, the best guidance stands alone. The company's
    passages keep the scores their own search gave them (`Models.rerank`)."""
    found = store.fused(conn, version_id, query, models.embed, channel="guidance")
    candidates = store.load_passages(conn, found[: config.TOP_K])
    if not candidates:
        return []
    pool = [*company, *candidates]
    ranked = rerank_top(query, pool, models.rerank, len(pool))
    own = {passage.id for passage in company}
    places = [n for n, passage in enumerate(ranked) if passage.id in own]
    last = places[-1] if places else len(ranked)
    above = [passage for passage in ranked[:last] if passage.id not in own]
    return above[: config.GUIDANCE_PER_SEARCH]


def searched(conn: store.Connection, version_id: int, query: str) -> list[Passage]:
    """One search as an answer makes it, in every channel: the company's top places,
    then the pictures and guidance it adds, within an answer's limits
    (`answer.with_extras`: X44 F2, X45 amendment 1). The evaluation sets score it."""
    models = answer_models()
    company = retriever(conn, version_id, models)(query)[: config.TOP_K]
    added = extras(conn, version_id, models)(query, company)
    return list(with_extras(company, added))


def ask_and_record(
    question: str, on_stage: Callable[[str], None] = no_stage
) -> tuple[Answer, int]:
    """Answer from the served Postgres index and store the audit record; return the
    answer and the record's id. `on_stage` hears each stage as it starts."""
    with telemetry.span("answer"), connect() as conn:
        version_id = served_index(conn)
        started = time.perf_counter()
        models = answer_models()
        retrieve, chat = with_stages(
            retriever(conn, version_id, models), llm.chat, on_stage
        )
        scoped = scoped_retriever(conn, version_id, models)
        extra = extras(conn, version_id, models)
        result = answer(question, retrieve, chat, scoped, extra)
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
    """Whether answers can be served and recorded: Postgres is reachable and the
    index to serve exists, embedded with the configured model."""
    try:
        with connect() as conn:
            served_index(conn)
    except IngestError:
        return False
    return True


def served_index(conn: store.Connection) -> int:
    """The index version to serve: `LIMESPEC_INDEX_VERSION` when set (a candidate
    evaluated before it goes live), otherwise the live one. Either must have been
    embedded with the configured model: question vectors from another model would
    not match its passage vectors."""
    if config.INDEX_VERSION:
        if not config.INDEX_VERSION.isdigit():
            raise IngestError("LIMESPEC_INDEX_VERSION must be an index version number")
        served = store.index_version(conn, int(config.INDEX_VERSION))
        if served is None:
            raise IngestError(f"no index version {config.INDEX_VERSION} to serve")
    else:
        served = store.live_version(conn)
        if served is None:
            raise IngestError(
                "no live Postgres index; run `uv run --env-file .env limespec ingest`"
            )
    version_id, embedding_model = served
    if embedding_model != config.EMBEDDING_MODEL:
        raise IngestError(
            f"index version {version_id} was embedded with {embedding_model}, but the "
            f"configured model is {config.EMBEDDING_MODEL}; rebuild it with "
            "`limespec ingest`"
        )
    return version_id

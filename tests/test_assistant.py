"""The one call behind every interface, end to end with fake model servers."""

from typing import Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from limespec import assistant, config, llm, store
from limespec.answer import PROMPT_SHA256, answer
from limespec.ingest import IngestError, prepare_index
from limespec.models import Passage
from limespec.retrieve import Embed, Rerank


def two_days_chat(system: str, user: str, schema: dict[str, Any]) -> object:
    """A stand-in model: no emergency, and one claim quoting the setting time."""
    if "describes_exposure" in schema["properties"]:
        asked = user.removeprefix("Question: ")
        return {
            "describes_exposure": False,
            "search_questions": [
                {"question": asked, "items": [], "asks_what_a_picture_shows": False}
            ],
        }
    blocks = user.split('<passage id="')[1:]
    source = next(b.split('"')[0] for b in blocks if "About two days" in b)
    claim = {
        "part": 1,
        "evidence": [{"source_id": source, "quote": "About two days"}],
        "text": "Mortex takes about two days to set.",
    }
    return {"claims": [claim]}


def live_postgres_index(
    pg: store.Connection,
    pages: list[tuple[str, bytes, str]],
    embed: Embed,
    embedding_model: str = config.EMBEDDING_MODEL,
) -> int:
    prepared = prepare_index(pages, embed)
    manifest = {**prepared.manifest, "embedding_model": embedding_model}
    version = store.write_version(
        pg, prepared.pages, prepared.passages, prepared.vectors, manifest
    )
    store.set_live(pg, version)
    pg.commit()
    return version


def test_ask_answers_from_the_live_index_with_both_model_requests(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    postgres_url: str,
    pg: store.Connection,
) -> None:
    live_postgres_index(pg, fixture_pages, fake_embed_1024)
    requests: list[dict[str, Any]] = []
    reranked: list[str] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        reranked.append(query)
        return [0.0] * len(documents)

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        requests.append(schema)
        return two_days_chat(system, user, schema)

    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    monkeypatch.setattr(llm, "rerank", rerank)
    monkeypatch.setattr(llm, "chat", chat)

    result = assistant.ask("How long does Mortex take to set?")

    assert len(requests) == 2  # the emergency request, then the answer request
    assert reranked == ["How long does Mortex take to set?"]
    assert result.status == "answered"
    assert result.claims[0].evidence[0].url == "https://example.test/support/faq"
    assert len(result.passages) <= config.TOP_K


def test_every_postgres_answer_is_recorded_for_audit(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    fake_rerank: Rerank,
    postgres_url: str,
    pg: store.Connection,
) -> None:
    version = live_postgres_index(pg, fixture_pages, fake_embed_1024)
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    monkeypatch.setattr(llm, "rerank", fake_rerank)
    monkeypatch.setattr(llm, "chat", two_days_chat)

    result, answer_id = assistant.ask_and_record("How long does Mortex take to set?")

    row = pg.execute(
        "SELECT question, status, shown->'claims'->0->>'text', removed, passage_ids, "
        "index_version_id, embedding_model, prompt_sha256, seconds "
        "FROM answers WHERE id = %s",
        (answer_id,),
    ).fetchone()
    assert row is not None
    (
        question,
        status,
        claim,
        removed,
        passage_ids,
        version_id,
        model,
        prompt,
        seconds,
    ) = row
    assert (question, status) == ("How long does Mortex take to set?", "answered")
    assert claim == "Mortex takes about two days to set."
    assert removed == []
    assert passage_ids == [p.id for p in result.passages]
    assert (version_id, model, prompt) == (
        version,
        config.EMBEDDING_MODEL,
        PROMPT_SHA256,
    )
    assert seconds > 0


def test_postgres_without_a_live_index_explains_what_to_run(
    monkeypatch: pytest.MonkeyPatch, postgres_url: str, pg: store.Connection
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)

    with pytest.raises(IngestError, match="no live Postgres index"):
        assistant.ask("anything")


def test_an_index_embedded_by_another_model_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    postgres_url: str,
    pg: store.Connection,
) -> None:
    live_postgres_index(pg, fixture_pages, fake_embed_1024, "other-embedder")
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)

    with pytest.raises(IngestError, match="embedded with other-embedder"):
        assistant.ask("anything")


def test_an_unreachable_postgres_is_an_ingest_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://x:y@127.0.0.1:9/z")
    monkeypatch.setattr(config, "DATABASE_CONNECT_TIMEOUT_SECONDS", 1)

    with pytest.raises(IngestError, match="cannot reach the Postgres index"):
        assistant.ask("anything")


def test_each_stage_is_reported_as_it_starts(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    fake_rerank: Rerank,
    postgres_url: str,
    pg: store.Connection,
) -> None:
    live_postgres_index(pg, fixture_pages, fake_embed_1024)
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    monkeypatch.setattr(llm, "rerank", fake_rerank)
    monkeypatch.setattr(llm, "chat", two_days_chat)
    stages: list[str] = []

    result, _ = assistant.ask_and_record(
        "How long does Mortex take to set?", stages.append
    )

    assert result.status == "answered"
    assert stages == ["understanding", "searching", "answering", "checking"]


def test_a_safety_referral_reports_only_understanding() -> None:
    stages: list[str] = []

    def never_searched(query: str) -> list[Passage]:
        raise AssertionError("an emergency is never searched")

    retrieve, chat = assistant.with_stages(
        never_searched,
        lambda system, user, schema: {
            "describes_exposure": True,
            "search_questions": [
                {"question": "q", "items": [], "asks_what_a_picture_shows": False}
            ],
        },
        stages.append,
    )

    result = answer("my son swallowed some mortar", retrieve, chat)

    assert result.status == "safety_referral"
    assert stages == ["understanding"]


def test_a_chosen_version_is_served_in_place_of_the_live_one(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    pg: store.Connection,
) -> None:
    live = live_postgres_index(pg, fixture_pages, fake_embed_1024)
    candidate = live_postgres_index(pg, fixture_pages, fake_embed_1024)
    store.set_live(pg, live)  # the candidate was built, then the live one restored

    assert assistant.served_index(pg) == live
    monkeypatch.setattr(config, "INDEX_VERSION", str(candidate))
    assert assistant.served_index(pg) == candidate
    monkeypatch.setattr(config, "INDEX_VERSION", "999999")
    with pytest.raises(IngestError, match="no index version 999999 to serve"):
        assistant.served_index(pg)
    monkeypatch.setattr(config, "INDEX_VERSION", "latest")
    with pytest.raises(IngestError, match="must be an index version number"):
        assistant.served_index(pg)


def test_recording_an_answer_needs_the_postgres_url() -> None:
    with pytest.raises(IngestError, match="LIMESPEC_DATABASE_URL is not set"):
        assistant.ask_and_record("anything")


def test_the_database_is_ready_only_with_a_matching_live_index(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    postgres_url: str,
    pg: store.Connection,
) -> None:
    assert assistant.database_ready() is False  # no URL set
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    assert assistant.database_ready() is False  # no live index yet

    live_postgres_index(pg, fixture_pages, fake_embed_1024)

    assert assistant.database_ready() is True


def test_an_answer_is_traced_stage_by_stage_without_its_text(
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    fake_rerank: Rerank,
    postgres_url: str,
    pg: store.Connection,
    spans: InMemorySpanExporter,
) -> None:
    version = live_postgres_index(pg, fixture_pages, fake_embed_1024)
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    monkeypatch.setattr(llm, "rerank", fake_rerank)
    monkeypatch.setattr(llm, "chat", two_days_chat)

    _, answer_id = assistant.ask_and_record("How long does Mortex take to set?")

    finished = {span.name: span for span in spans.get_finished_spans()}
    answer_span = finished["answer"]
    for stage in ["understanding", "searching", "answering"]:
        parent = finished[stage].parent
        assert parent is not None and parent.span_id == answer_span.context.span_id
    assert answer_span.attributes is not None
    assert dict(answer_span.attributes) == {
        "limespec.index.version": version,
        "limespec.answer.id": answer_id,
        "limespec.answer.status": "answered",
        "limespec.claims.kept": 1,
        "limespec.claims.removed": 0,
    }


def test_one_answer_embeds_and_scores_each_pair_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from limespec import siglip

    asked: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        asked.append(texts)
        return [[float(len(text))] for text in texts]

    scored: list[list[str]] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        scored.append(documents)
        return [float(len(document)) for document in documents]

    monkeypatch.setattr(llm, "embed", embed)
    monkeypatch.setattr(llm, "rerank", rerank)
    monkeypatch.setattr(siglip, "text_vector", lambda query: [float(len(query))])
    models = assistant.answer_models()

    assert models.embed(["ab", "abc", "ab"]) == [[2.0], [3.0], [2.0]]
    assert models.embed(["abc"]) == [[3.0]]
    assert asked == [["ab", "abc"]]
    assert models.rerank("q", ["a", "bb"]) == [1.0, 2.0]
    assert models.rerank("q", ["bb", "ccc"]) == [2.0, 3.0]
    assert scored == [["a", "bb"], ["ccc"]]  # "bb" was scored once
    assert models.picture("Duro") is models.picture("Duro")  # started once
    assert models.picture("Duro").result() == [4.0]


def picture(number: int) -> Passage:
    return Passage(number, "u", "T", "Image", "", "", image=f"p{number}")


def text_passage(number: int) -> Passage:
    return Passage(number, "u", "T", "", f"text {number}", "")


def test_a_search_adds_its_best_pictures_then_guidance_on_merit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from limespec import siglip

    channels: list[str] = []

    def fused(conn: Any, version: int, query: str, embed: Any, **opts: Any) -> Any:
        channels.append(opts["channel"])
        return [7, 5] if opts["channel"] == "picture" else [30, 31, 32]

    def load(conn: Any, found: list[int]) -> list[Passage]:
        return [picture(n) if n < 10 else text_passage(n) for n in found]

    def rerank(query: str, documents: list[str]) -> list[float]:
        # Guidance 30 beats every company passage, 31 only the last, 32 none.
        scores = {"text 1": 5.0, "text 2": 3.0, "text 30": 9.0, "text 31": 4.0}
        return [scores.get(document.split("\n")[-1], 0.0) for document in documents]

    monkeypatch.setattr(store, "picture_passages", lambda conn, v: {"p5": 5})
    monkeypatch.setattr(store, "picture_ranking", lambda conn, v, vector, n: [5, 6])
    monkeypatch.setattr(store, "fused", fused)
    monkeypatch.setattr(store, "load_passages", load)
    monkeypatch.setattr(siglip, "text_vector", lambda query: [1.0])
    monkeypatch.setattr(llm, "rerank", rerank)
    add = assistant.extras(None, 21)  # type: ignore[arg-type]

    found = add("Show me Duro", [text_passage(1), text_passage(2)])

    # Words' best two (7, 5), then SigLIP2's (5 again, 6), then guidance on merit.
    assert [p.id for p in found] == [7, 5, 6, 30, 31]
    assert channels == ["picture", "guidance"]
    assert [p.id for p in add("Duro", [])] == [7, 5, 6, 30, 31]  # best guidance alone


def test_a_version_without_pictures_or_guidance_adds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "picture_passages", lambda conn, v: {})
    monkeypatch.setattr(store, "fused", lambda *args, **opts: [])
    monkeypatch.setattr(store, "load_passages", lambda conn, found: [])

    assert assistant.extras(None, 4)("Duro", [text_passage(1)]) == []  # type: ignore[arg-type]


def test_a_search_as_an_answer_makes_it_is_every_channel_s_places(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from limespec import siglip

    company = [text_passage(n) for n in range(1, 11)]
    monkeypatch.setattr(store, "search", lambda conn, v, q, embed, rerank, top: company)
    monkeypatch.setattr(siglip, "text_vector", lambda query: [1.0])
    pictures = [picture(n) for n in range(50, 56)]
    monkeypatch.setattr(
        assistant, "extras", lambda conn, v, models: lambda q, top: pictures
    )

    found = assistant.searched(None, 21, "Duro")  # type: ignore[arg-type]

    # The company's top 8, then at most MAX_PICTURES pictures (X45 amendment 1).
    assert [p.id for p in found] == [*range(1, 9), 50, 51, 52, 53]

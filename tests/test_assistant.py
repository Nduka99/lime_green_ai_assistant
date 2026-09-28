"""The one call behind every interface, end to end with fake model servers."""

from pathlib import Path
from typing import Any

import pytest

from limespec import assistant, config, llm, store
from limespec.ingest import IngestError, build_index, prepare_index
from limespec.retrieve import Embed, Rerank


def test_a_missing_index_explains_what_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "DATABASE", tmp_path / "missing.db")

    with pytest.raises(IngestError, match="run `limespec ingest` first"):
        assistant.ask("anything")


def test_an_index_path_that_cannot_be_opened_explains_how_to_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "directory-not-a-database"
    database.mkdir()
    monkeypatch.setattr(config, "DATABASE", database)

    with pytest.raises(IngestError, match="run `limespec ingest` to rebuild it"):
        assistant.ask("anything")


def test_ask_answers_from_the_index_with_both_model_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed: Embed,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)
    requests: list[dict[str, Any]] = []
    reranked: list[str] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        reranked.append(query)
        return [0.0] * len(documents)

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        requests.append(schema)
        if "describes_exposure" in schema["properties"]:
            return {"describes_exposure": False}
        blocks = user.split('<passage id="')[1:]
        source = next(b.split('"')[0] for b in blocks if "About two days" in b)
        claim = {
            "evidence": [{"source_id": source, "quote": "About two days"}],
            "text": "Mortex takes about two days to set.",
        }
        return {"claims": [claim], "answers_every_part": True}

    monkeypatch.setattr(config, "DATABASE", database)
    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(llm, "rerank", rerank)
    monkeypatch.setattr(llm, "chat", chat)

    result = assistant.ask("How long does Mortex take to set?")

    assert len(requests) == 2  # the emergency request, then the answer request
    assert reranked == ["How long does Mortex take to set?"]
    assert result.status == "answered"
    assert result.claims[0].evidence[0].url == "https://example.test/support/faq"


def two_days_chat(system: str, user: str, schema: dict[str, Any]) -> object:
    """A stand-in model: no emergency, and one claim quoting the setting time."""
    if "describes_exposure" in schema["properties"]:
        return {"describes_exposure": False}
    blocks = user.split('<passage id="')[1:]
    source = next(b.split('"')[0] for b in blocks if "About two days" in b)
    claim = {
        "evidence": [{"source_id": source, "quote": "About two days"}],
        "text": "Mortex takes about two days to set.",
    }
    return {"claims": [claim], "answers_every_part": True}


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


def test_ask_answers_from_the_live_postgres_index_when_configured(
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

    result = assistant.ask("How long does Mortex take to set?")

    assert result.status == "answered"
    assert result.claims[0].evidence[0].url == "https://example.test/support/faq"
    assert len(result.passages) <= config.TOP_K


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

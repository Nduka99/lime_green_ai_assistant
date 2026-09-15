"""The one call behind every interface, end to end with fake model servers."""

from pathlib import Path
from typing import Any

import pytest

from limespec import assistant, config, llm
from limespec.ingest import IngestError, build_index
from limespec.retrieve import Embed


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

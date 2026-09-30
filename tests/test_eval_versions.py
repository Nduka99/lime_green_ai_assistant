"""Index versions for experiments, against the throwaway Postgres (the `pg` fixture).
Pages, passages and vectors are invented."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from evaluation import __main__ as cli
from evaluation import versions
from limespec import assistant, llm, store

PAGES = [
    ("https://example.test/duro", "Duro Render", "2026-09-12T10:00:00+00:00", "sha-d"),
    ("https://example.test/faq.pdf", "FAQ", "2026-09-12T11:30:00+00:00", "sha-f"),
]
PASSAGES: list[store.PassageRow] = [
    ("https://example.test/duro", "Duro Render", "Duro Render",
     "Duro renders are free of cement.", "", None),
    ("https://example.test/faq.pdf", "FAQ", "Delivery",
     "We deliver on weekdays.", "Orders › Delivery", 3),
]  # fmt: skip
MANIFEST = {"corpus_sha256": "c", "passages_sha256": "p", "embedding_model": "old"}


def one_hot(place: int) -> list[float]:
    return [1.0 if n == place else 0.0 for n in range(1024)]


def test_a_version_embedded_again_keeps_its_passages_with_new_vectors(
    pg: store.Connection,
) -> None:
    original = store.write_version(
        pg, PAGES, PASSAGES, [one_hot(0), one_hot(1)], MANIFEST
    )
    read: list[str] = []

    def embed(texts: list[str]) -> list[list[float]]:
        read.extend(texts)
        return [one_hot(3 + n) for n in range(len(texts))]

    copy = versions.embedded_again(pg, original, embed, "new-embedder")

    assert copy != original
    assert read == [
        "Duro Render\nDuro renders are free of cement.",
        "FAQ\nOrders › Delivery\nWe deliver on weekdays.",
    ]
    row = pg.execute(
        "SELECT corpus_sha256, passages_sha256, embedding_model FROM index_versions "
        "WHERE id = %s",
        (copy,),
    ).fetchone()
    assert row == ("c", "p", "new-embedder")
    [passage] = store.load_passages(pg, store.keyword_ranking(pg, copy, "weekdays", 5))
    assert (passage.context, passage.page) == ("Orders › Delivery", 3)
    [nearest] = store.load_passages(pg, store.vector_ranking(pg, copy, one_hot(4), 1))
    assert nearest.heading == "Delivery"  # the new vectors, not the old ones
    with pytest.raises(ValueError, match="no index version 99"):
        versions.embedded_again(pg, 99, embed, "new-embedder")


def test_the_command_line_embeds_a_version_again_with_another_server(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    calls: list[tuple[int, str, list[list[float]]]] = []

    def again(conn: None, version: int, embed: versions.Embed, model: str) -> int:
        calls.append((version, model, embed(["text"])))
        return 14

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(versions, "embedded_again", again)
    monkeypatch.setattr(llm, "embed", lambda texts, url: [[float(len(url))]])

    code = cli.main(
        ["embed-again", "--version", "12", "--url", "http://x", "--model", "big"]
    )

    assert code == 0
    assert calls == [(12, "big", [[8.0]])]
    assert "version 14" in capsys.readouterr().out

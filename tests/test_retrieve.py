import sqlite3
from pathlib import Path

import pytest

from limespec import config
from limespec.ingest import build_index
from limespec.retrieve import (
    Embed,
    Rerank,
    fuse,
    keyword_ranking,
    search,
    vector_ranking,
)


def test_fusion_rewards_agreement_and_breaks_ties_by_id() -> None:
    # Passages 1 and 3 appear in both rankings with equal fused scores; 2 and 4 once.
    assert fuse([[3, 1, 2], [1, 3, 4]]) == [1, 3, 2, 4]


def test_fixture_pages_ingest_and_retrieve_end_to_end(
    tmp_path: Path,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed: Embed,
    fake_rerank: Rerank,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)

    with sqlite3.connect(database) as conn:
        best = search(
            conn, "How long does Mortex take to set?", fake_embed, fake_rerank
        )[0]

    assert best.url == "https://example.test/support/faq"
    assert best.title == "Questions"
    assert best.heading == "How long does Mortex take to set?"
    assert best.fetched_at == "2026-09-12T10:00:00+00:00"


def test_the_reranker_orders_the_fused_candidates_and_the_top_k_are_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed: Embed,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)
    monkeypatch.setattr(config, "RERANK_CANDIDATES", 6)
    monkeypatch.setattr(config, "TOP_K", 3)
    seen: list[str] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        seen.extend(documents)
        return [float(len(document)) for document in documents]  # longest first

    with sqlite3.connect(database) as conn:
        found = search(conn, "Mortex mortar joints", fake_embed, rerank)

    assert len(seen) == 6  # every fused candidate is scored, with its page title
    assert all("\n" in document for document in seen)
    lengths = [len(f"{p.title}\n{p.text}") for p in found]
    assert lengths == sorted((len(document) for document in seen), reverse=True)[:3]


def test_equal_scores_keep_the_fused_order(
    tmp_path: Path,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed: Embed,
    fake_rerank: Rerank,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)

    with sqlite3.connect(database) as conn:
        query_vector = fake_embed([config.QUERY_INSTRUCTION + "lime render"])[0]
        fused = fuse(
            [
                keyword_ranking(conn, "lime render", config.CANDIDATES_PER_METHOD),
                vector_ranking(conn, query_vector, config.CANDIDATES_PER_METHOD),
            ]
        )
        found = search(conn, "lime render", fake_embed, fake_rerank)

    assert [p.id for p in found] == fused[: config.TOP_K]


def test_an_empty_index_returns_no_passages_without_calling_the_reranker(
    fake_embed: Embed,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE passages_fts USING fts5(text)")
    conn.execute("CREATE TABLE passages (id INTEGER PRIMARY KEY, embedding BLOB)")

    def rerank(query: str, documents: list[str]) -> list[float]:
        raise AssertionError("nothing to rerank")

    assert search(conn, "anything", fake_embed, rerank) == []


def test_keyword_search_treats_query_syntax_as_plain_words(
    tmp_path: Path, fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)

    with sqlite3.connect(database) as conn:
        assert keyword_ranking(conn, 'NOT "Mortex" OR (timber)?', 5)
        assert keyword_ranking(conn, "?!", 5) == []

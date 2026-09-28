import pytest

from limespec import config, store
from limespec.ingest import prepare_index
from limespec.models import Passage
from limespec.retrieve import Embed, Rerank, fuse, rerank_top


def candidates(count: int) -> list[Passage]:
    """Passages whose texts grow longer, in fused order."""
    return [
        Passage(i, "https://example.test/p", f"Page {i}", "Section", "x" * i, "")
        for i in range(1, count + 1)
    ]


def test_fusion_rewards_agreement_and_breaks_ties_by_id() -> None:
    # Passages 1 and 3 appear in both rankings with equal fused scores; 2 and 4 once.
    assert fuse([[3, 1, 2], [1, 3, 4]]) == [1, 3, 2, 4]


def test_fixture_pages_ingest_and_retrieve_end_to_end(
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    fake_rerank: Rerank,
    pg: store.Connection,
) -> None:
    prepared = prepare_index(fixture_pages, fake_embed_1024)
    version = store.write_version(
        pg, prepared.pages, prepared.passages, prepared.vectors, prepared.manifest
    )

    best = store.search(
        pg, version, "How long does Mortex take to set?", fake_embed_1024, fake_rerank
    )[0]

    assert best.url == "https://example.test/support/faq"
    assert best.title == "Questions"
    assert best.heading == "How long does Mortex take to set?"
    assert best.fetched_at == "2026-09-12T10:00:00+00:00"


def test_the_reranker_orders_the_fused_candidates_and_the_top_k_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "TOP_K", 3)
    seen: list[str] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        seen.extend(documents)
        return [float(len(document)) for document in documents]  # longest first

    found = rerank_top("Mortex mortar joints", candidates(6), rerank)

    assert len(seen) == 6  # every fused candidate is scored, with its page title
    assert all(document.startswith("Page ") for document in seen)
    assert [p.id for p in found] == [6, 5, 4]


def test_equal_scores_keep_the_fused_order(fake_rerank: Rerank) -> None:
    found = rerank_top("lime render", candidates(10), fake_rerank)

    assert [p.id for p in found] == list(range(1, config.TOP_K + 1))


def test_no_candidates_are_returned_without_calling_the_reranker() -> None:
    def rerank(query: str, documents: list[str]) -> list[float]:
        raise AssertionError("nothing to rerank")

    assert rerank_top("anything", [], rerank) == []

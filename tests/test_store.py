"""The Postgres index, tested against a real Postgres 18 with pgvector in a
throwaway database (see the `pg` fixture). Pages and vectors are invented."""

import math

import pytest

from limespec import store

PAGES = [
    ("https://example.test/products/duro", "Duro Render", "2026-09-12T10:00:00+00:00",
     "sha-duro"),
    ("https://example.test/support/faq", "FAQ", "2026-09-12T11:30:00+01:00",
     "sha-faq"),
]  # fmt: skip
PASSAGES = [
    ("https://example.test/products/duro", "Duro Render", "Duro Render",
     "Duro Render\nDuro renders are free of cement."),
    ("https://example.test/support/faq", "FAQ", "Delivery",
     "Delivery\nWe deliver on weekdays."),
    ("https://example.test/support/faq", "FAQ", "Samples",
     "Samples\nThe sample pack holds three colours."),
]  # fmt: skip
# Two dimensions padded to the column's 1024; each passage points a different way.
VECTORS = [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]]
MANIFEST = {
    "corpus_sha256": "corpus",
    "passages_sha256": "passages",
    "embedding_model": "test-embedder",
}


def padded(vector: list[float]) -> list[float]:
    return vector + [0.0] * (1024 - len(vector))


def build(pg: store.Connection) -> int:
    return store.write_version(
        pg, PAGES, PASSAGES, [padded(v) for v in VECTORS], MANIFEST
    )


def test_vectors_are_sent_as_unit_length_text() -> None:
    text = store.vector_text([3.0, 4.0])

    assert text == "[0.6,0.8]"
    values = [float(x) for x in text.strip("[]").split(",")]
    assert math.isclose(sum(v * v for v in values), 1.0)


def test_a_new_version_is_stored_but_not_live(pg: store.Connection) -> None:
    version = build(pg)

    counts = pg.execute(
        "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM passages)"
    ).fetchone()
    assert counts == (2, 3)
    assert store.live_version(pg) is None
    row = pg.execute(
        "SELECT embedding_model, live FROM index_versions WHERE id = %s", (version,)
    ).fetchone()
    assert row == ("test-embedder", False)


def test_an_unchanged_page_is_stored_once_across_versions(
    pg: store.Connection,
) -> None:
    first = build(pg)
    second = build(pg)

    assert second != first
    assert pg.execute("SELECT count(*) FROM documents").fetchone() == (2,)
    assert pg.execute("SELECT count(*) FROM passages").fetchone() == (6,)


def test_one_version_is_live_at_a_time(pg: store.Connection) -> None:
    first = build(pg)
    second = build(pg)

    store.set_live(pg, first)
    assert store.live_version(pg) == (first, "test-embedder")
    store.set_live(pg, second)
    assert store.live_version(pg) == (second, "test-embedder")
    live = pg.execute("SELECT count(*) FROM index_versions WHERE live").fetchone()
    assert live == (1,)


def test_making_an_unknown_version_live_changes_nothing(
    pg: store.Connection,
) -> None:
    version = build(pg)
    store.set_live(pg, version)

    with pytest.raises(ValueError, match="no index version 999"):
        store.set_live(pg, 999)
    assert store.live_version(pg) == (version, "test-embedder")


def test_keyword_ranking_matches_any_stemmed_word(pg: store.Connection) -> None:
    version = build(pg)

    # "rendering" stems to "render"; "the" is a stop word; "sample" matches too.
    found = store.keyword_ranking(pg, version, "The rendering sample?", 10)

    passages = store.load_passages(pg, found)
    assert {p.heading for p in passages} == {"Duro Render", "Samples"}


def test_keyword_ranking_without_words_finds_nothing(pg: store.Connection) -> None:
    version = build(pg)

    assert store.keyword_ranking(pg, version, "?!", 10) == []
    assert store.keyword_ranking(pg, version, "the and", 10) == []


def test_vector_ranking_orders_by_cosine_within_one_version(
    pg: store.Connection,
) -> None:
    first = build(pg)
    second = build(pg)

    found = store.vector_ranking(pg, second, padded([0.0, 2.0]), 3)

    headings = [p.heading for p in store.load_passages(pg, found)]
    assert headings == ["Delivery", "Samples", "Duro Render"]
    older = store.vector_ranking(pg, first, padded([0.0, 2.0]), 3)
    assert set(found).isdisjoint(older)


def test_loaded_passages_keep_the_given_order_and_utc_capture_time(
    pg: store.Connection,
) -> None:
    version = build(pg)
    ids = store.vector_ranking(pg, version, padded([1.0, 0.0]), 3)

    passages = store.load_passages(pg, list(reversed(ids)))

    assert [p.id for p in passages] == list(reversed(ids))
    faq = next(p for p in passages if p.heading == "Delivery")
    assert faq.url == "https://example.test/support/faq"
    assert faq.title == "FAQ"
    assert faq.fetched_at == "2026-09-12T10:30:00+00:00"  # 11:30 at +01:00
    assert faq.text.startswith("Delivery\n")

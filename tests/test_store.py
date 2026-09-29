"""The Postgres index, tested against a real Postgres 18 with pgvector in a
throwaway database (see the `pg` fixture). Pages and vectors are invented."""

import math

import psycopg
import pytest

from limespec import store

PAGES = [
    ("https://example.test/products/duro", "Duro Render", "2026-09-12T10:00:00+00:00",
     "sha-duro"),
    ("https://example.test/support/faq", "FAQ", "2026-09-12T11:30:00+01:00",
     "sha-faq"),
]  # fmt: skip
PASSAGES: list[store.PassageRow] = [
    ("https://example.test/products/duro", "Duro Render", "Duro Render",
     "Duro Render\nDuro renders are free of cement.", "", None),
    ("https://example.test/support/faq", "FAQ", "Delivery",
     "Delivery\nWe deliver on weekdays.", "", None),
    ("https://example.test/support/faq", "FAQ", "Samples",
     "Samples\nThe sample pack holds three colours.", "", None),
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


def test_a_pdf_passage_keeps_its_page_and_is_found_by_its_context(
    pg: store.Connection,
) -> None:
    pdf = ("https://example.test/duro.pdf", "Duro Render — Data Sheet",
           "2026-09-12T10:00:00+00:00", "sha-pdf")  # fmt: skip
    table = (
        "https://example.test/duro.pdf",
        "Duro Render — Data Sheet",
        "Performance",
        "Fire | Class A1",
        "Performance › Reaction class",
        2,
    )
    version = store.write_version(
        pg, [*PAGES, pdf], [*PASSAGES, table],
        [padded(v) for v in [*VECTORS, [0.8, 0.6]]], MANIFEST,
    )  # fmt: skip

    found = store.keyword_ranking(pg, version, "reaction class", 10)

    [passage] = store.load_passages(pg, found)
    assert (passage.text, passage.page) == ("Fire | Class A1", 2)
    assert passage.context == "Performance › Reaction class"
    [web] = store.load_passages(pg, store.keyword_ranking(pg, version, "weekdays", 10))
    assert (web.page, web.context) == (None, "")


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

    # "rendering" stems to "render"; "sample" and the stop word "the" also match.
    found = store.keyword_ranking(pg, version, "The rendering sample?", 10)

    passages = store.load_passages(pg, found)
    assert {p.heading for p in passages} == {"Duro Render", "Samples"}


def test_keyword_ranking_counts_stop_words_such_as_not(pg: store.Connection) -> None:
    [(words,)] = pg.execute(
        "SELECT to_tsvector(%s, 'Do not apply renders')::text", (store.KEYWORD_CONFIG,)
    ).fetchall()

    # Stemmed like `english`, but "do" and "not" are kept: "not" carries meaning.
    assert words == "'appli':3 'do':1 'not':2 'render':4"


def test_keyword_ranking_without_a_matching_word_finds_nothing(
    pg: store.Connection,
) -> None:
    version = build(pg)

    assert store.keyword_ranking(pg, version, "?!", 10) == []
    assert store.keyword_ranking(pg, version, "zebra xylophone", 10) == []


def test_keyword_ranking_reads_query_syntax_as_plain_words(
    pg: store.Connection,
) -> None:
    version = build(pg)

    found = store.keyword_ranking(pg, version, 'NOT "Samples" OR (render)?', 10)

    headings = {p.heading for p in store.load_passages(pg, found)}
    assert headings == {"Samples", "Duro Render"}


def test_each_version_has_its_own_bm25_index_removed_with_it(
    pg: store.Connection,
) -> None:
    first = build(pg)
    second = build(pg)
    store.set_live(pg, second)

    names = {
        row[0]
        for row in pg.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'passages_bm25_v%'"
        ).fetchall()
    }
    assert names == {store.bm25_index(first), store.bm25_index(second)}
    store.delete_version(pg, first)
    assert pg.execute("SELECT count(*) FROM passages").fetchone() == (3,)
    remaining = pg.execute(
        "SELECT count(*) FROM pg_indexes WHERE indexname = %s",
        (store.bm25_index(first),),
    ).fetchone()
    assert remaining == (0,)
    assert store.keyword_ranking(pg, second, "sample", 10) != []


def test_search_fuses_both_rankings_then_reranks(pg: store.Connection) -> None:
    version = build(pg)

    def embed(texts: list[str]) -> list[list[float]]:
        return [padded([0.0, 1.0]) for _ in texts]  # nearest: Delivery, then Samples

    def rerank(query: str, documents: list[str]) -> list[float]:
        return [1.0 if "sample pack" in d else 0.0 for d in documents]

    found = store.search(pg, version, "When do you deliver?", embed, rerank)

    # The reranker's pick first; the rest keep their fused order (Delivery matched
    # both the keyword and the vector ranking, so it leads the fused list).
    assert [p.heading for p in found] == ["Samples", "Delivery", "Duro Render"]


def test_an_answer_record_round_trips_as_plain_data(pg: store.Connection) -> None:
    version = build(pg)
    shown = {"status": "answered", "claims": [{"text": "Duro has no cement."}]}
    removed = [{"text": "Duro is cheap.", "reason": "quote not in S1"}]

    answer_id = store.record_answer(
        pg,
        question="Does Duro contain cement?",
        status="answered",
        shown=shown,
        removed=removed,
        passage_ids=[3, 1],
        index_version_id=version,
        embedding_model="test-embedder",
        prompt_sha256="abc",
        seconds=1.5,
    )

    row = pg.execute(
        "SELECT question, status, shown, removed, passage_ids, index_version_id, "
        "embedding_model, prompt_sha256, seconds, created_at IS NOT NULL "
        "FROM answers WHERE id = %s",
        (answer_id,),
    ).fetchone()
    assert row == (
        "Does Duro contain cement?", "answered", shown, removed, [3, 1], version,
        "test-embedder", "abc", 1.5, True,
    )  # fmt: skip


def test_an_answer_s_given_passages_are_read_back_in_order(
    pg: store.Connection,
) -> None:
    version = build(pg)
    ids = [p.id for p in store.document_passages(pg, version, PASSAGES[1][0])]
    answer_id = store.record_answer(
        pg, "q", "answered", {}, [], list(reversed(ids)), version, "e", "p", 1.0
    )

    used, passages = store.given_passages(pg, answer_id)

    assert used == version
    assert [p.id for p in passages] == list(reversed(ids))
    with pytest.raises(ValueError, match="no answer record"):
        store.given_passages(pg, answer_id + 1000)


def test_an_unknown_status_is_refused_by_the_database(pg: store.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        store.record_answer(
            pg, question="q", status="maybe", shown={}, removed=[], passage_ids=[],
            index_version_id=1, embedding_model="m", prompt_sha256="p", seconds=0.1,
        )  # fmt: skip


def test_the_live_version_cannot_be_deleted(pg: store.Connection) -> None:
    version = build(pg)
    store.set_live(pg, version)

    with pytest.raises(ValueError, match="not live"):
        store.delete_version(pg, version)
    assert store.live_version(pg) == (version, "test-embedder")


def test_a_passage_with_a_price_is_stored_but_never_searched(
    pg: store.Connection,
) -> None:
    priced: list[store.PassageRow] = [
        *PASSAGES[:2],
        ("https://example.test/support/faq", "FAQ", "Samples",
         "Samples\nThe sample pack costs £5.00 and holds three colours.", "",
         None),
    ]  # fmt: skip
    version = store.write_version(
        pg, PAGES, priced, [padded(v) for v in VECTORS], MANIFEST
    )

    tagged = pg.execute(
        "SELECT heading FROM passages WHERE index_version_id = %s AND commercial",
        (version,),
    ).fetchall()
    assert tagged == [("Samples",)]
    keyword = store.keyword_ranking(pg, version, "sample pack colours", 10)
    vector = store.vector_ranking(pg, version, padded([0.6, 0.8]), 10)
    found = store.load_passages(pg, keyword + vector)
    assert "Samples" not in {p.heading for p in found}
    assert len(vector) == 2


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


def test_a_document_s_passages_and_a_version_s_size_are_read(
    pg: store.Connection,
) -> None:
    version = build(pg)

    faq = store.document_passages(pg, version, "https://example.test/support/faq")

    assert [p.heading for p in faq] == ["Delivery", "Samples"]
    assert store.passage_count(pg, version) == 3
    assert store.document_passages(pg, version, "https://example.test/none") == []


def test_only_passages_search_can_return_are_counted_as_searchable(
    pg: store.Connection,
) -> None:
    priced: list[store.PassageRow] = [
        *PASSAGES[:2],
        ("https://example.test/support/faq", "FAQ", "Samples", "Samples cost £5.",
         "", None),
    ]  # fmt: skip
    version = store.write_version(
        pg, PAGES, priced, [padded(v) for v in VECTORS], MANIFEST
    )

    assert store.searchable_texts(pg, version) == [row[3] for row in PASSAGES[:2]]

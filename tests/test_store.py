"""The Postgres index, tested against a real Postgres 18 with pgvector in a
throwaway database (see the `pg` fixture). Pages and vectors are invented."""

import math
import uuid

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


def bm25_names(pg: store.Connection) -> set[str]:
    return {
        row[0]
        for row in pg.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'passages_bm25_v%'"
        ).fetchall()
    }


def test_each_version_has_a_bm25_index_per_channel_removed_with_it(
    pg: store.Connection,
) -> None:
    first = build(pg)
    second = build(pg)
    store.set_live(pg, second)

    assert bm25_names(pg) == {
        store.bm25_index(version, channel)
        for version in (first, second)
        for channel in store.CHANNELS
    }
    store.delete_version(pg, first)
    assert pg.execute("SELECT count(*) FROM passages").fetchone() == (3,)
    assert bm25_names(pg) == {store.bm25_index(second, c) for c in store.CHANNELS}
    assert store.keyword_ranking(pg, second, "sample", 10) != []


def test_guidance_passages_do_not_move_the_company_keyword_scores(
    pg: store.Connection,
) -> None:
    guide = ("https://example.test/guide.pdf", "GOV.UK — Guide",
             "2026-09-12T10:00:00+00:00", "sha-guide")  # fmt: skip
    # Words the company passages share, repeated, change BM25's word statistics.
    extra = [
        (guide[0], guide[1], f"Part {n}", "Delivery samples delivery samples", "", 1)
        for n in range(6)
    ]
    alone = build(pg)
    beside = store.write_version(
        pg, [*PAGES, guide], [*PASSAGES, *extra],
        [padded(v) for v in [*VECTORS, *[[0.5, 0.5]] * 6]], MANIFEST,
    )  # fmt: skip

    def scores(version: int) -> list[tuple[str, float]]:
        rows = pg.execute(
            "SELECT heading, (title || ' ' || context || ' ' || text) "
            "<@> to_bm25query('delivery samples', %s) FROM passages "
            "WHERE index_version_id = %s AND channel = 'company' ORDER BY heading",
            (store.bm25_index(version, "company"), version),
        ).fetchall()
        return [(heading, round(score, 9)) for heading, score in rows]

    assert scores(beside) == scores(alone)
    assert store.keyword_ranking(pg, beside, "delivery", 10, channel="guidance")


def test_a_version_without_channel_indexes_names_the_command(
    pg: store.Connection,
) -> None:
    version = build(pg)
    pg.execute(f'DROP INDEX "{store.bm25_index(version, "company")}"')

    with pytest.raises(ValueError, match=f"keyword-index --version {version}"):
        store.keyword_ranking(pg, version, "sample", 10)


def test_keyword_indexes_keep_the_indexes_a_version_has(
    pg: store.Connection,
) -> None:
    version = build(pg)
    pg.execute(f'DROP INDEX "{store.bm25_index(version, "picture")}"')

    store.keyword_indexes(pg, version)
    store.keyword_indexes(pg, version)

    assert bm25_names(pg) == {store.bm25_index(version, c) for c in store.CHANNELS}


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


def test_an_answer_s_removed_claims_are_read_back_with_their_reasons(
    pg: store.Connection,
) -> None:
    version = build(pg)
    removed = [{"text": "Duro is cheap.", "reason": "does not answer the question"}]
    answer_id = store.record_answer(
        pg, "q", "answered", {}, removed, [], version, "e", "p", 1.0
    )

    assert store.removed_claims(pg, answer_id) == removed
    with pytest.raises(ValueError, match="no answer record"):
        store.removed_claims(pg, answer_id + 1000)


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


def test_a_build_finds_the_vectors_the_newest_version_of_its_embedder_stored(
    pg: store.Connection,
) -> None:
    assert store.known_vectors(pg, "test-embedder") == {}
    build(pg)
    newest = build(pg)
    pg.execute(
        "UPDATE passages SET text = 'changed' WHERE index_version_id <> %s", (newest,)
    )

    known = store.known_vectors(pg, "test-embedder")

    key = ("FAQ", "", "Delivery\nWe deliver on weekdays.")
    assert len(known) == 3 and known[key][:2] == [0.0, 1.0]
    assert store.known_vectors(pg, "another-embedder") == {}


def test_each_channel_is_searched_apart_and_a_picture_needs_words_of_its_own(
    pg: store.Connection,
) -> None:
    guidance = ("https://gov.test/adl.pdf", "GOV.UK — Approved Document L",
                "2026-09-12T10:00:00+00:00", "sha-adl")  # fmt: skip
    rows: list[store.PassageRow] = [
        *PASSAGES,
        (guidance[0], guidance[1], "Walls", "Walls must limit heat loss.", "", 4),
        (PAGES[0][0], "Duro Render", "Image", "", "Image › Uses", None),
        (PAGES[0][0], "Duro Render", "Image", "", "Image › Uses\nA rendered wall",
         None),
    ]  # fmt: skip
    vectors = [padded(v) for v in [*VECTORS, [0.0, 1.0], [1.0, 0.0], [1.0, 0.0]]]
    images = ["", "", "", "", "a" * 64, "b" * 64]
    pictures = {"a" * 64: b"a", "b" * 64: b"b"}
    version = store.write_version(
        pg, [*PAGES, guidance], rows, vectors, MANIFEST, images, pictures
    )

    def channel_of(passage_id: int) -> str:
        row = pg.execute("SELECT channel FROM passages WHERE id = %s", (passage_id,))
        return str(row.fetchone()[0])  # type: ignore[index]

    walls = store.keyword_ranking(pg, version, "walls", 10, channel="guidance")
    wall_pictures = store.keyword_ranking(pg, version, "wall", 10, channel="picture")

    assert [channel_of(n) for n in walls] == ["guidance"]
    assert store.keyword_ranking(pg, version, "walls", 10) == []
    assert len(wall_pictures) == 1  # the picture with no words is not searched by words
    assert store.load_passages(pg, wall_pictures)[0].image == "b" * 64
    fused = store.fused(pg, version, "walls", lambda texts: [padded([0.0, 1.0])])
    assert fused and all(channel_of(n) == "company" for n in fused)
    assert store.channel("Duro", "") == "company"


def test_a_picture_is_stored_once_and_named_by_its_passage(
    pg: store.Connection,
) -> None:
    picture = "a" * 64
    image_row: store.PassageRow = (
        "https://example.test/products/duro", "Duro Render", "Image",
        "A wall pointed with lime mortar", "Image › Uses", None,
    )  # fmt: skip
    rows = [*PASSAGES, image_row]
    vectors = [padded(v) for v in [*VECTORS, [0.8, 0.6]]]
    images = ["", "", "", picture]
    siglip = [1.0] + [0.0] * 1151
    for _ in range(2):  # a second version reuses the stored picture
        version = store.write_version(
            pg, PAGES, rows, vectors, MANIFEST, images, {picture: b"png"},
            {picture: siglip},
        )  # fmt: skip

    ranked = store.keyword_ranking(pg, version, "pointed", 10, channel="picture")
    found = store.load_passages(pg, ranked)

    assert [(p.image, p.heading) for p in found] == [(picture, "Image")]
    assert store.keyword_ranking(pg, version, "pointed", 10) == []  # company only
    assert store.picture_ranking(pg, version, siglip, 5) == ranked
    assert store.picture_passages(pg, version) == {picture: found[0].id}
    assert pg.execute("SELECT count(*) FROM images").fetchone() == (1,)


LIMITS = (30, 8, 20)  # idle minutes, hours since the start, turns


def record_turn(
    pg: store.Connection, version: int, conversation_id: str, turn: int, text: str
) -> int:
    """Record an answer for one turn whose shown view is a single claim `text`."""
    shown = {"claims": [{"text": text}], "notice": ""}
    return store.record_answer(
        pg, f"question {turn}", "answered", shown, [], [], version, "e", "p", 1.0,
        conversation_id=conversation_id, turn=turn,
    )  # fmt: skip


def test_a_question_without_a_conversation_starts_one_at_turn_one(
    pg: store.Connection,
) -> None:
    opened = store.open_turn(pg, None, *LIMITS)

    assert opened is not None
    conversation_id, turn = opened
    assert uuid.UUID(conversation_id).version == 4  # random, made by the server
    assert turn == 1


def test_each_turn_of_a_conversation_takes_the_next_number(
    pg: store.Connection,
) -> None:
    opened = store.open_turn(pg, None, *LIMITS)
    assert opened is not None
    conversation_id = opened[0]

    numbers = [store.open_turn(pg, conversation_id, *LIMITS) for _ in range(2)]

    assert numbers == [(conversation_id, 2), (conversation_id, 3)]


def test_an_unknown_conversation_has_no_next_turn(pg: store.Connection) -> None:
    assert store.open_turn(pg, str(uuid.uuid4()), *LIMITS) is None


@pytest.mark.parametrize(
    ("change", "open_again"),
    [
        ("last_active_at = now() - interval '29 minutes'", True),
        ("last_active_at = now() - interval '31 minutes'", False),
        ("created_at = now() - interval '9 hours'", False),  # however active
        ("turns = 20", False),
    ],
)
def test_a_conversation_ends_when_idle_too_old_or_full(
    pg: store.Connection, change: str, open_again: bool
) -> None:
    opened = store.open_turn(pg, None, *LIMITS)
    assert opened is not None
    pg.execute(f"UPDATE conversations SET {change}")  # the test's own literal SQL

    assert (store.open_turn(pg, opened[0], *LIMITS) is not None) == open_again


def test_earlier_turns_are_the_last_answers_before_the_turn_oldest_first(
    pg: store.Connection,
) -> None:
    version = build(pg)
    ids = []
    for conversation in range(2):
        opened = store.open_turn(pg, None, *LIMITS)
        assert opened is not None
        ids.append(opened[0])
        for turn in range(1, 6):
            if turn > 1:
                store.open_turn(pg, opened[0], *LIMITS)
            record_turn(pg, version, opened[0], turn, f"reply {conversation}.{turn}")

    earlier = store.earlier_turns(pg, ids[0], 6, 4)
    first_two = store.earlier_turns(pg, ids[0], 3, 4)

    assert earlier == [
        (f"question {turn}", {"claims": [{"text": f"reply 0.{turn}"}], "notice": ""})
        for turn in range(2, 6)
    ]
    assert [question for question, _ in first_two] == ["question 1", "question 2"]


def test_an_answer_in_a_conversation_keeps_its_turn_and_search_questions(
    pg: store.Connection,
) -> None:
    version = build(pg)
    opened = store.open_turn(pg, None, *LIMITS)
    assert opened is not None

    answer_id = store.record_answer(
        pg, "and Solo?", "answered", {}, [], [], version, "e", "p", 1.0,
        search_questions=["What is Solo?"], conversation_id=opened[0], turn=1,
    )  # fmt: skip

    row = pg.execute(
        "SELECT conversation_id::text, turn, search_questions FROM answers "
        "WHERE id = %s",
        (answer_id,),
    ).fetchone()
    assert row == (opened[0], 1, ["What is Solo?"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        record_turn(pg, version, opened[0], 1, "the same turn twice")


def test_a_turn_needs_its_conversation_and_a_conversation_its_turn(
    pg: store.Connection,
) -> None:
    version = build(pg)

    with pytest.raises(psycopg.errors.CheckViolation):
        store.record_answer(pg, "q", "answered", {}, [], [], version, "e", "p", 1.0,
                            turn=1)  # fmt: skip

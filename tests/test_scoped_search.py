"""A search repeated inside the products a question names (E5 B4). The store parts run
against the throwaway Postgres (the `pg` fixture); pages and vectors are invented."""

import pytest

from limespec import answer, assistant, config, llm, store
from limespec.models import Passage

SITE = config.SITE
SDS = "Section 4\nRinse the eye with water."
PAGES = [
    (f"{SITE}products/ad2", "Silic8 AD2", "2026-09-12T10:00:00+00:00", "sha-ad2"),
    (f"{SITE}products/ad2.pdf", "AD2 SDS", "2026-09-12T10:00:00+00:00", "sha-ad2-sds"),
    (f"{SITE}products/mpl1", "Silic8 MPL1", "2026-09-12T10:00:00+00:00", "sha-mpl1"),
    (
        f"{SITE}products/mpl1.pdf",
        "MPL1 SDS",
        "2026-09-12T10:00:00+00:00",
        "sha-mpl1-sds",
    ),
    (f"{SITE}news/open-day", "Open day", "2026-09-12T10:00:00+00:00", "sha-news"),
]
PASSAGES: list[store.PassageRow] = [
    (f"{SITE}products/ad2", "Silic8 AD2", "Silic8 AD2", "AD2 repairs lath.", "", None),
    (f"{SITE}products/ad2.pdf", "Silic8 AD2 — SDS", "", SDS, "First aid", 2),
    (f"{SITE}products/mpl1", "Silic8 MPL1", "Silic8 MPL1", "MPL1 primes.", "", None),
    (f"{SITE}products/mpl1.pdf", "Silic8 MPL1 — SDS", "", SDS, "First aid", 2),
    (f"{SITE}news/open-day", "Open day", "Open day", "We showed AD2.", "", None),
]  # fmt: skip
MANIFEST = {"corpus_sha256": "c", "passages_sha256": "p", "embedding_model": "e"}


def one_hot(place: int) -> list[float]:
    return [1.0 if n == place else 0.0 for n in range(1024)]


def build(pg: store.Connection) -> int:
    vectors = [one_hot(n) for n in range(len(PASSAGES))]
    return store.write_version(pg, PAGES, PASSAGES, vectors, MANIFEST)


def test_rankings_can_keep_only_the_named_products(pg: store.Connection) -> None:
    version = build(pg)
    ad2 = ["Silic8 AD2"]

    kept = store.load_passages(pg, store.keyword_ranking(pg, version, "eye", 10, ad2))
    near = store.vector_ranking(pg, version, one_hot(3), 5, ad2)

    assert [p.title for p in kept] == ["Silic8 AD2 — SDS"]  # MPL1's copy left out
    assert {p.title for p in store.load_passages(pg, near)} == {
        "Silic8 AD2",
        "Silic8 AD2 — SDS",
    }
    assert len(store.keyword_ranking(pg, version, "eye", 10)) == 2  # no scope, both
    assert store.product_names(pg, version) == ["Silic8 AD2", "Silic8 MPL1"]


def test_the_scoped_retriever_searches_only_named_products(
    pg: store.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = build(pg)
    monkeypatch.setattr(llm, "embed", lambda texts: [one_hot(1) for _ in texts])
    monkeypatch.setattr(llm, "rerank", lambda q, docs: [float(len(d)) for d in docs])
    retrieve = assistant.scoped_retriever(pg, version)

    # With two products, "silic8" is in both names, and still names them.
    named = retrieve("what does the silic8 ad2 sds say about eyes")

    assert {p.title for p in named} == {"Silic8 AD2", "Silic8 AD2 — SDS"}
    assert len(named) <= config.SCOPED_TOP
    assert retrieve("what about the open day") == []


def passage(passage_id: int, title: str, text: str) -> Passage:
    return Passage(
        passage_id, f"https://example.test/{passage_id}", title, "", text, ""
    )


def test_named_passages_follow_the_others_and_replace_other_products_copies() -> None:
    mpl1_sds = passage(1, "Silic8 MPL1 — SDS", SDS)
    guide = passage(2, "Lath guide", "Use AD2 on laths.")
    ad2_sds = passage(3, "Silic8 AD2 — SDS", SDS)
    ad2_page = passage(4, "Silic8 AD2", "AD2 repairs lath.")

    merged = answer.with_own_copies([mpl1_sds, guide], [ad2_sds, ad2_page])

    # AD2's own copy of the shared text is cited in place of MPL1's.
    assert merged == (ad2_sds, guide, ad2_page)
    # A copy that is already a named product's stays.
    both = answer.with_own_copies([ad2_sds, guide], [passage(5, "Silic8 AD2", SDS)])
    assert both == (ad2_sds, guide)


def test_named_passages_stay_within_the_budget() -> None:
    found = [passage(n, "Guide", f"text {n}") for n in range(config.PASSAGE_BUDGET)]

    merged = answer.with_own_copies(found, [passage(99, "Silic8 AD2", "new text")])

    assert merged == tuple(found)


def test_gather_adds_each_search_s_named_products() -> None:
    searched: list[str] = []
    guide = passage(2, "Lath guide", "Use AD2 on laths.")
    ad2_page = passage(4, "Silic8 AD2", "AD2 repairs lath.")

    def scoped(query: str) -> list[Passage]:
        searched.append(query)
        return [ad2_page] if "AD2" in query else []

    given = answer.gather(
        ["Is AD2 for laths?", "Is MPL1 a primer?"], lambda q: [guide], scoped
    )

    assert searched == ["Is AD2 for laths? Is MPL1 a primer?", "Is AD2 for laths?",
                        "Is MPL1 a primer?"]  # fmt: skip
    assert given == (guide, ad2_page)
    assert answer.gather(["q"], lambda q: [guide]) == (guide,)  # no scoped search

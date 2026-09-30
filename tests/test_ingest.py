import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from limespec import config, store
from limespec.ingest import (
    IngestError,
    cache_path,
    corpus_hash,
    extract_sections,
    fetch_missing,
    fetch_page,
    file_links,
    file_title,
    ingest,
    page_passages,
    page_url,
    pdf_titles,
    prepare_index,
    read_sources,
    site_html,
    site_pages,
    split_section,
)
from limespec.retrieve import Embed

FIXTURES = Path(__file__).parent / "fixtures"
SITE = "https://example.test/"


def sections_of(name: str) -> tuple[str, list[tuple[str, list[str]]]]:
    return extract_sections((FIXTURES / name).read_text(encoding="utf-8"))


# --- Extraction -------------------------------------------------------------


def test_product_page_keeps_content_and_drops_site_furniture() -> None:
    title, sections = sections_of("product.html")

    assert title == "Mortex Base Coat"
    assert sections == [
        (
            "Mortex Base Coat",
            [
                "Mortex is a lime base coat for solid walls.",
                "Finish it with one coat of Velour or Satin Top.",
            ],
        ),
        ("Product uses", ["Stone walls\nNot for timber"]),  # a list: one paragraph
    ]


def test_each_faq_question_and_answer_form_one_section() -> None:
    _, sections = sections_of("faq.html")

    assert sections == [
        ("How long does Mortex take to set?", ["About two days in mild weather."]),
        ("Do you deliver on Saturdays?", ["No, deliveries run Monday to Friday."]),
    ]


def test_page_without_main_is_read_from_the_body() -> None:
    title, sections = sections_of("category.html")

    assert title == "Base Coats"
    assert sections == [
        ("Base Coats", ["Our base coats level and protect walls before the finish."]),
        ("Mortex Base Coat", ["A lime base coat for solid walls."]),
    ]


def test_do_and_dont_lists_stay_with_their_heading() -> None:
    title, sections = sections_of("article.html")

    assert title == "Rendering Checklist"
    assert sections == [
        # Each list is one paragraph with the lead-in that ends in a colon.
        ("Application", ["Do:\nWork with a wet edge.", "Don't:\nApply below 5°C."]),
        ("Inspection", ["Look at the wall square on."]),  # a heading-styled <p>
    ]


def test_a_bold_line_starts_a_section_under_the_same_heading() -> None:
    html = (
        "<body><h2>Plastics</h2><p>Waste is rising.</p>"
        "<p><strong>How can we limit it?</strong></p>"
        "<ol><li>Plan ahead.</li><li>Use natural materials.</li></ol>"
        "<p><b>What</b> <strong>next?</strong></p><p>Hybrid materials.</p>"
        "<p><strong>Lime is not cement.</strong></p>"  # a sentence, not a sub-heading
        f"<p><strong>{'A long bold paragraph ' * 10}</strong></p></body>"
    )

    _, sections = extract_sections(html)

    assert [heading for heading, _ in sections] == ["Plastics"] * 3
    assert sections[0][1] == ["Waste is rising."]
    assert sections[1][1] == [
        "How can we limit it?",
        "Plan ahead.\nUse natural materials.",
    ]
    assert sections[2][1][:3] == [
        "What next?",
        "Hybrid materials.",
        "Lime is not cement.",
    ]
    assert len(sections[2][1]) == 4  # the long bold paragraph stays in the section


def test_a_bold_line_right_after_a_heading_is_its_first_paragraph() -> None:
    html = "<body><h2>Uses</h2><p><strong>Indoors</strong></p><p>Walls.</p></body>"

    assert extract_sections(html)[1] == [("Uses", ["Indoors", "Walls."])]


def test_two_lists_in_a_row_stay_two_paragraphs() -> None:
    html = (
        "<body><h2>Uses</h2><p>Good for:</p><ul><li>walls</li><li>floors</li></ul>"
        "<ul><li>not roofs</li></ul><p>See the guide.</p></body>"
    )

    assert extract_sections(html)[1] == [
        ("Uses", ["Good for:\nwalls\nfloors", "not roofs", "See the guide."])
    ]


def test_items_written_as_paragraphs_are_still_one_list() -> None:
    html = (
        "<body><h2>Types</h2><ul><li><p>Putty</p></li><li><p>NHL</p></li></ul></body>"
    )

    assert extract_sections(html)[1] == [("Types", ["Putty\nNHL"])]


def test_a_page_without_a_body_is_an_error() -> None:
    with pytest.raises(ValueError, match="no <body>"):
        extract_sections("")


# --- Splitting and duplicates ------------------------------------------------


def test_long_section_splits_at_paragraph_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MAX_PASSAGE_CHARS", 40)
    a, b, c = "a" * 15, "b" * 15, "c" * 15

    assert split_section("H", [a, b, c]) == [f"H\n{a}\n{b}", f"H\n{c}"]


def test_a_list_stays_whole_when_it_fits_and_splits_between_items_when_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MAX_PASSAGE_CHARS", 40)
    intro, short = "i" * 20, "Use:\n" + "a" * 10 + "\n" + "b" * 10
    long_list = "c" * 20 + "\n" + "d" * 20 + "\n" + "e" * 10

    # The list does not fit beside the intro, so it moves whole to a new passage.
    assert split_section("H", [intro, short]) == [f"H\n{intro}", f"H\n{short}"]
    assert split_section("H", [long_list]) == [
        "H\n" + "c" * 20,
        "H\n" + "d" * 20 + "\n" + "e" * 10,
    ]


def test_long_paragraph_splits_at_sentences_within_the_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MAX_PASSAGE_CHARS", 60)
    paragraph = (
        "Lime sets slowly in cold weather. Protect fresh work from frost. "
        "A semi-circular arch over a doorway needs a sentence longer than "
        "the whole budget, so it wraps at spaces."
    )

    passages = split_section("Curing", [paragraph])

    assert all(len(passage) <= 60 for passage in passages)
    assert passages[0] == "Curing\nLime sets slowly in cold weather."
    body = " ".join(passage.removeprefix("Curing\n") for passage in passages)
    assert " ".join(body.split()) == paragraph  # nothing lost, no word broken


def test_every_fixture_passage_respects_the_maximum() -> None:
    for name in ("product.html", "faq.html", "category.html", "article.html"):
        _, passages = page_passages((FIXTURES / name).read_text(encoding="utf-8"))
        assert all(len(text) <= config.MAX_PASSAGE_CHARS for _, text in passages)


def test_repeated_text_within_a_page_is_kept_once() -> None:
    html = "<body><h2>Uses</h2><p>Walls.</p><h2>Uses</h2><p>Walls.</p></body>"

    assert page_passages(html) == ("", [("Uses", "Uses\nWalls.")])


# --- Index --------------------------------------------------------------------


def test_an_index_keeps_passages_per_page_with_exact_byte_hashes(
    fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    # The same page under a second URL keeps its own passages and provenance.
    copy_url = "https://example.test/copy"
    windows_bytes = fixture_pages[0][1].replace(b"\n", b"\r\n")
    copy = (copy_url, windows_bytes, fixture_pages[0][2])

    prepared = prepare_index([*fixture_pages, copy], fake_embed)

    assert prepared.manifest["pages"] == "5"
    # 10 page passages and the category page's compiled product list (X12).
    assert prepared.manifest["passages"] == "11"
    assert len(prepared.vectors) == 11
    hashes = {url: sha256 for url, _, _, sha256 in prepared.pages}
    assert hashes[copy_url] == hashlib.sha256(windows_bytes).hexdigest()
    assert sum(row[0] == copy_url for row in prepared.passages) == 2
    faq_text = next(
        text
        for _, _, heading, text, *_ in prepared.passages
        if heading.startswith("How")
    )
    assert (
        faq_text == "How long does Mortex take to set?\nAbout two days in mild weather."
    )


def test_a_price_sentence_is_left_out_of_the_index(fake_embed: Embed) -> None:
    html = (
        "<body><h2>Samples</h2><p>A pack costs £5.00. It holds three colours.</p>"
        "<h2>Fee</h2><p>The fee is £10.</p></body>"
    )
    page = (SITE + "samples", html.encode(), "2026-01-01T00:00:00+00:00")

    prepared = prepare_index([page], fake_embed)

    # The second section keeps nothing but its heading, so it is not indexed.
    assert [row[3] for row in prepared.passages] == ["Samples\nIt holds three colours."]


def test_corpus_hash_depends_on_urls_and_hashes_not_order() -> None:
    pages = [("https://example.test/a", "1" * 64), ("https://example.test/b", "2" * 64)]

    assert corpus_hash(pages) == corpus_hash(list(reversed(pages)))
    assert corpus_hash(pages) != corpus_hash(
        [pages[0], ("https://example.test/c", "2" * 64)]
    )


def test_passage_hash_ignores_byte_changes_that_do_not_change_the_text(
    tmp_path: Path, fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    # The live site differs between downloads only in a render-time stamp.
    url, raw, fetched = fixture_pages[0]
    stamped = raw.replace(b"</main>", b'<span data-rt="0.02"></span></main>')

    first = prepare_index([(url, raw, fetched)], fake_embed).manifest
    second = prepare_index([(url, stamped, fetched)], fake_embed).manifest

    assert first["corpus_sha256"] != second["corpus_sha256"]
    assert first["passages_sha256"] == second["passages_sha256"]


def test_a_pdf_joins_the_index_with_its_page_and_context(
    fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    url = "https://example.test/duro.pdf"
    page_row = (url, "Duro Render — Data Sheet", "2026-09-12T10:00:00+00:00", "sha")
    row = (url, page_row[1], "Performance", "Fire | Class A1", "Performance", 2)
    read: list[str] = []

    def embed(texts: list[str]) -> list[list[float]]:
        read.extend(texts)
        return fake_embed(texts)

    prepared = prepare_index(fixture_pages[:1], embed, [(page_row, [row])])
    moved = prepare_index(fixture_pages[:1], embed, [(page_row, [(*row[:5], 3)])])

    assert prepared.pages[-1] == page_row and prepared.passages[-1] == row
    assert read[-1] == "Duro Render — Data Sheet\nPerformance\nFire | Class A1"
    assert prepared.manifest["passages_sha256"] != moved.manifest["passages_sha256"]


def test_a_failed_rebuild_leaves_the_live_index_intact(
    cached_faq: Path, pg: store.Connection, fake_embed_1024: Embed
) -> None:
    first, _ = ingest(pg, fake_embed_1024)
    pg.commit()

    def one_vector_short(texts: list[str]) -> list[list[float]]:
        return fake_embed_1024(texts)[:-1]

    with pytest.raises(ValueError):
        ingest(pg, one_vector_short)
    pg.rollback()

    assert store.live_version(pg) == (first, config.EMBEDDING_MODEL)
    assert pg.execute("SELECT count(*) FROM index_versions").fetchone() == (1,)


@pytest.mark.parametrize(
    ("raw", "reason"), [(b"\xff\xfe not utf-8", "utf-8"), (b"", "no <body>")]
)
def test_an_unreadable_page_is_reported_with_its_url(
    fake_embed: Embed, raw: bytes, reason: str
) -> None:
    pages = [("https://example.test/broken", raw, "2026-09-12T10:00:00+00:00")]

    with pytest.raises(IngestError, match=f"https://example.test/broken: .*{reason}"):
        prepare_index(pages, fake_embed)


# --- Sources and the whole ingest --------------------------------------------


def test_read_sources_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    sources = tmp_path / "sources.txt"
    sources.write_text(
        "# rule\n  # indented note\n\n"
        "https://example.test/a\n https://example.test/b \n"
    )

    assert read_sources(sources) == ["https://example.test/a", "https://example.test/b"]


def test_a_version_can_be_built_without_going_live(
    cached_faq: Path, pg: store.Connection, fake_embed_1024: Embed
) -> None:
    live, _ = ingest(pg, fake_embed_1024)
    candidate, _ = ingest(pg, fake_embed_1024, cached_faq, live=False)

    assert candidate != live
    assert store.live_version(pg) == (live, config.EMBEDDING_MODEL)
    assert store.index_version(pg, candidate) == (candidate, config.EMBEDDING_MODEL)


def test_ingest_makes_a_new_version_live_from_the_cache(
    cached_faq: Path, pg: store.Connection, fake_embed_1024: Embed
) -> None:
    first, _ = ingest(pg, fake_embed_1024)
    second, manifest = ingest(pg, fake_embed_1024)

    assert store.live_version(pg) == (second, config.EMBEDDING_MODEL)
    assert second != first
    assert (manifest["pages"], manifest["passages"]) == ("1", "2")
    found = store.keyword_ranking(pg, second, "Do you deliver on Saturdays?", 5)
    [top] = store.load_passages(pg, found[:1])
    assert top.url == "https://example.test/support/faq"
    assert top.heading == "Do you deliver on Saturdays?"


# --- Polite acquisition --------------------------------------------------------


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def offline_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[httpx.Request], list[float]]:
    """Point the crawler at example.test with a temporary cache and no real sleeps."""
    monkeypatch.setattr(config, "SITE", SITE)
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path / "site")
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return requests, sleeps


def transport(requests: list[httpx.Request], handler: Handler) -> httpx.MockTransport:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.MockTransport(record)


def site(robots: httpx.Response) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots
        return httpx.Response(200, content=f"<p>{request.url.path}</p>".encode())

    return handler


def test_crawl_reads_robots_first_identifies_itself_and_waits_after_each_request(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, sleeps = offline_site
    urls = [SITE + "a", SITE + "b"]

    fetch_missing(
        urls,
        transport(requests, site(httpx.Response(200, text="User-agent: *\nAllow: /"))),
    )

    assert [request.url.path for request in requests] == ["/robots.txt", "/a", "/b"]
    assert all(r.headers["User-Agent"] == config.USER_AGENT for r in requests)
    assert sleeps == [config.REQUEST_DELAY_SECONDS] * 3
    assert cache_path(SITE + "b").read_bytes() == b"<p>/b</p>"


def test_crawl_refuses_a_page_disallowed_by_robots(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, _ = offline_site
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /private")

    with pytest.raises(IngestError, match="https://example.test/private/x: disallowed"):
        fetch_missing([SITE + "private/x"], transport(requests, site(robots)))
    assert [request.url.path for request in requests] == ["/robots.txt"]


def test_a_redirected_robots_file_is_followed_but_a_moved_page_is_not(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, _ = offline_site

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(301, headers={"Location": SITE + "rules.txt"})
        if request.url.path == "/rules.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"Location": SITE + "elsewhere"})

    with pytest.raises(IngestError, match="https://example.test/private/x: disallowed"):
        fetch_missing([SITE + "private/x"], transport(requests, handler))
    with pytest.raises(IngestError, match="https://example.test/moved: HTTP 302"):
        fetch_missing([SITE + "moved"], transport(requests, handler))
    assert "/elsewhere" not in [request.url.path for request in requests]


def test_missing_robots_file_allows_everything(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, _ = offline_site

    fetch_missing([SITE + "a"], transport(requests, site(httpx.Response(404))))

    assert cache_path(SITE + "a").exists()


def test_unreachable_robots_file_stops_the_crawl(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, _ = offline_site

    with pytest.raises(IngestError, match="https://example.test/robots.txt: HTTP 500"):
        fetch_missing([SITE + "a"], transport(requests, site(httpx.Response(500))))


def test_a_failed_page_names_its_url_and_status(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, _ = offline_site

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(503)

    with pytest.raises(IngestError, match="https://example.test/a: HTTP 503"):
        fetch_missing([SITE + "a"], transport(requests, handler))


def test_a_connection_error_names_the_url() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with (
        httpx.Client(transport=httpx.MockTransport(refuse)) as client,
        pytest.raises(IngestError, match="https://example.test/a: connection refused"),
    ):
        fetch_page(client, SITE + "a")


def test_cached_pages_are_never_downloaded_again(
    offline_site: tuple[list[httpx.Request], list[float]],
) -> None:
    requests, sleeps = offline_site
    cache_path(SITE + "a").parent.mkdir()
    cache_path(SITE + "a").write_bytes(b"<p>cached</p>")

    fetch_missing([SITE + "a"], transport(requests, site(httpx.Response(200))))

    assert requests == [] and sleeps == []


PRODUCT = """<html><body><main><h1>Duro Render</h1><p>A lime render.</p>
<a href="/Documents/duro%20tds.pdf">Data Sheet</a> <a href="/Documents/sds.pdf"> </a>
<img src="/images/bag.png" alt="Duro bag"></main></body></html>"""
QUESTIONS = """<html><body><main><h1>Questions</h1><p>Ask us.</p>
<a href="/Documents/duro%20tds.pdf">TDS</a> <a href="/Documents/faq.pdf">FAQ sheet</a>
</main></body></html>"""


def test_pdfs_are_titled_by_the_pages_that_link_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)
    (tmp_path / "support__faq.html").write_text(QUESTIONS, encoding="utf-8")
    (tmp_path / "products__duro.html").write_text(PRODUCT, encoding="utf-8")
    site = config.SITE

    titles = pdf_titles(site_html())

    assert site_pages() == [site + "products/duro", site + "support/faq"]
    assert page_url("home") == site
    assert file_links(PRODUCT) == [
        ("document", site + "Documents/duro%20tds.pdf", "Data Sheet"),
        ("document", site + "Documents/sds.pdf", ""),
        ("image", site + "images/bag.png", "Duro bag"),
    ]
    assert titles == {
        site + "Documents/duro%20tds.pdf": "Duro Render — Data Sheet",  # product first
        site + "Documents/sds.pdf": "Duro Render",  # the link has no text
        site + "Documents/faq.pdf": "Questions — FAQ sheet",
    }
    assert file_title(site + "Documents/duro%20tds.pdf") == "duro tds"


def test_every_cached_page_and_a_pdf_can_be_indexed(
    cached_faq: Path, pg: store.Connection, fake_embed_1024: Embed
) -> None:
    url = "https://example.test/duro.pdf"
    title = "Duro — Data Sheet"
    row: store.PassageRow = (
        url,
        title,
        "Performance",
        "Fire | Class A1",
        "Performance",
        2,
    )
    document = ((url, title, "2026-09-12T10:00:00+00:00", "sha-pdf"), [row])

    version, manifest = ingest(
        pg, fake_embed_1024, live=False, all_pages=True, documents=[document]
    )

    assert manifest["pages"] == "2"
    assert pg.execute(
        "SELECT page, context FROM passages WHERE index_version_id = %s "
        "AND page IS NOT NULL",
        (version,),
    ).fetchall() == [(2, "Performance")]

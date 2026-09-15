import hashlib
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from limespec import config
from limespec.ingest import (
    IngestError,
    build_index,
    cache_path,
    corpus_hash,
    extract_sections,
    fetch_missing,
    fetch_page,
    ingest,
    page_passages,
    read_sources,
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
        ("Product uses", ["Stone walls", "Not for timber"]),
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
        ("Application", ["Do:", "Work with a wet edge.", "Don't:", "Apply below 5°C."]),
        ("Inspection", ["Look at the wall square on."]),  # a heading-styled <p>
    ]


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


def test_build_index_stores_passages_per_page_with_exact_byte_hashes(
    tmp_path: Path, fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    database = tmp_path / "index.db"
    # The same page under a second URL keeps its own passages and provenance.
    copy_url = "https://example.test/copy"
    windows_bytes = fixture_pages[0][1].replace(b"\n", b"\r\n")
    copy = (copy_url, windows_bytes, fixture_pages[0][2])

    manifest = build_index(database, [*fixture_pages, copy], fake_embed)

    assert manifest["pages"] == "5"
    assert manifest["passages"] == "10"
    with sqlite3.connect(database) as conn:
        stored = dict(conn.execute("SELECT url, sha256 FROM pages"))
        copy_passages = conn.execute(
            "SELECT count(*) FROM passages WHERE url = ?", (copy_url,)
        ).fetchone()[0]
        faq_text = conn.execute(
            "SELECT text FROM passages WHERE heading LIKE 'How long%'"
        ).fetchone()[0]
        stored_manifest = dict(conn.execute("SELECT key, value FROM meta"))
    assert stored[copy_url] == hashlib.sha256(windows_bytes).hexdigest()
    assert copy_passages == 2
    assert (
        faq_text == "How long does Mortex take to set?\nAbout two days in mild weather."
    )
    assert stored_manifest == manifest


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

    first = build_index(tmp_path / "a.db", [(url, raw, fetched)], fake_embed)
    second = build_index(tmp_path / "b.db", [(url, stamped, fetched)], fake_embed)

    assert first["corpus_sha256"] != second["corpus_sha256"]
    assert first["passages_sha256"] == second["passages_sha256"]


def test_a_failed_rebuild_leaves_the_previous_index_intact(
    tmp_path: Path, fixture_pages: list[tuple[str, bytes, str]], fake_embed: Embed
) -> None:
    database = tmp_path / "index.db"
    first = build_index(database, fixture_pages, fake_embed)

    def one_vector_short(texts: list[str]) -> list[list[float]]:
        return fake_embed(texts)[:-1]

    with pytest.raises(ValueError):
        build_index(database, fixture_pages, one_vector_short)

    with sqlite3.connect(database) as conn:
        assert dict(conn.execute("SELECT key, value FROM meta")) == first


@pytest.mark.parametrize(
    ("raw", "reason"), [(b"\xff\xfe not utf-8", "utf-8"), (b"", "no <body>")]
)
def test_an_unreadable_page_is_reported_with_its_url(
    tmp_path: Path, fake_embed: Embed, raw: bytes, reason: str
) -> None:
    pages = [("https://example.test/broken", raw, "2026-09-12T10:00:00+00:00")]

    with pytest.raises(IngestError, match=f"https://example.test/broken: .*{reason}"):
        build_index(tmp_path / "index.db", pages, fake_embed)


# --- Sources and the whole ingest --------------------------------------------


def test_read_sources_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    sources = tmp_path / "sources.txt"
    sources.write_text(
        "# rule\n  # indented note\n\n"
        "https://example.test/a\n https://example.test/b \n"
    )

    assert read_sources(sources) == ["https://example.test/a", "https://example.test/b"]


def test_ingest_reads_settings_when_called_and_builds_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_embed: Embed
) -> None:
    url = "https://example.test/support/faq"
    sources = tmp_path / "sources.txt"
    sources.write_text(f"# test\n{url}\n")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path / "site")
    monkeypatch.setattr(config, "SOURCES_FILE", sources)
    monkeypatch.setattr(config, "DATABASE", tmp_path / "index.db")
    cache_path(url).parent.mkdir()
    cache_path(url).write_bytes((FIXTURES / "faq.html").read_bytes())

    manifest = ingest(fake_embed)

    assert (tmp_path / "index.db").exists()
    assert (manifest["pages"], manifest["passages"]) == ("1", "2")


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

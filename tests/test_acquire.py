"""Collecting sources: pages into the page cache, documents and images into the
content-addressed store, politely, with failures reported. The site is invented."""

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from limespec import acquire, cli, config
from limespec.ingest import cache_path, polite_client

SITE = "https://example.test/"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
PDF = b"%PDF-1.7 a datasheet"


def handler(request: httpx.Request) -> httpx.Response:
    """A stand-in site: robots.txt, two copies of one PDF, a moved one, a missing one,
    one that cannot be reached, a sized and an unsized image, and pages."""
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS)
    if path in ("/docs/a.pdf", "/docs/copy-of-a.pdf"):
        headers = {"content-type": "application/pdf", "content-length": str(len(PDF))}
        return httpx.Response(200, content=PDF, headers=headers)
    if path == "/docs/moved.pdf":
        return httpx.Response(301, headers={"location": SITE + "docs/a.pdf"})
    if path == "/docs/boom.pdf":
        raise httpx.ConnectError("refused")
    if path == "/img/unsized.webp":
        return httpx.Response(200, content=b"")
    if path.startswith("/pages/") and path != "/pages/moved":
        return httpx.Response(200, content=f"<p>{path}</p>".encode())
    if path == "/pages/moved":
        return httpx.Response(301, headers={"location": SITE + "pages/new"})
    return httpx.Response(404)


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Point the collector at example.test with temporary stores, no real sleeps and
    every request answered by `handler`; yields the paths requested."""
    requested: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        requested.append(f"{request.method} {request.url.path}")
        return handler(request)

    monkeypatch.setattr(config, "SITE", SITE)
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path / "site")
    monkeypatch.setattr(config, "FILE_STORE", tmp_path / "files")
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        acquire,
        "polite_client",
        lambda transport=None: polite_client(httpx.MockTransport(record)),
    )
    yield requested


def test_a_sitemap_lists_its_pages_in_order() -> None:
    xml = "<urlset><url><loc> https://x.test/a </loc></url><url><loc>https://x.test/b</loc></url></urlset>"

    assert acquire.sitemap_urls(xml) == ["https://x.test/a", "https://x.test/b"]


def test_only_the_sites_own_pdfs_and_images_are_collected(site: list[str]) -> None:
    html = (
        '<a href="/docs/a.pdf">sheet</a><a href="https://cdn.example.test/b.PDF">b</a>'
        '<a href="https://www.gov.uk/guide.pdf">gov</a><a href="/products/">page</a>'
        '<img src="/img/photo.webp"><img src="https://tracker.test/pixel.gif">'
    )

    documents, images = acquire.linked_files(html)

    assert documents == [SITE + "docs/a.pdf", "https://cdn.example.test/b.PDF"]
    assert images == [SITE + "img/photo.webp"]


def test_files_are_stored_once_by_hash_and_failures_reported(site: list[str]) -> None:
    urls = [
        SITE + f"docs/{name}.pdf"
        for name in ["a", "copy-of-a", "moved", "gone", "boom"]
    ]
    urls.append(SITE + "private/c.pdf")

    results = acquire.acquire_files(urls, "document")

    sha256 = hashlib.sha256(PDF).hexdigest()
    by_url = {record["url"]: record for record in results}
    for name in ["a", "copy-of-a", "moved"]:  # a redirect is followed for a file
        assert by_url[SITE + f"docs/{name}.pdf"]["sha256"] == sha256
    assert by_url[SITE + "docs/gone.pdf"]["error"] == "HTTP 404"
    assert by_url[SITE + "docs/boom.pdf"]["error"] == "refused"
    assert by_url[SITE + "private/c.pdf"]["error"] == "disallowed by robots.txt"
    assert acquire.store_path(sha256).read_bytes() == PDF
    assert sorted(p.name for p in config.FILE_STORE.iterdir()) == [
        sha256,
        "manifest.json",
    ]
    manifest = acquire.read_manifest()
    assert [record["url"] for record in manifest] == urls[:3]
    assert manifest[0]["content_type"] == "application/pdf"
    assert manifest[0]["bytes"] == len(PDF)


def test_a_second_run_downloads_only_what_failed(site: list[str]) -> None:
    urls = [SITE + "docs/a.pdf", SITE + "docs/gone.pdf"]
    acquire.acquire_files(urls, "document")
    site.clear()

    retried = acquire.acquire_files(urls, "document")

    assert site == ["GET /robots.txt", "GET /docs/gone.pdf"]
    assert [record["url"] for record in retried] == [SITE + "docs/gone.pdf"]
    site.clear()
    assert acquire.acquire_files([SITE + "docs/a.pdf"], "document") == []
    assert site == []  # nothing left to fetch: not even robots.txt


def test_pages_are_cached_and_a_moved_page_is_reported(site: list[str]) -> None:
    config.PAGE_CACHE.mkdir()
    cache_path(SITE + "pages/cached").write_bytes(b"<p>old</p>")
    urls = [SITE + f"pages/{name}" for name in ["one", "moved", "cached"]]
    urls += [SITE + "private/page", SITE + "docs/boom.pdf"]

    results = acquire.acquire_pages(urls)

    assert cache_path(SITE + "pages/one").read_bytes() == b"<p>/pages/one</p>"
    assert results == [
        {"url": SITE + "pages/one", "bytes": len(b"<p>/pages/one</p>")},
        {"url": SITE + "pages/moved", "error": "HTTP 301"},
        {"url": SITE + "private/page", "error": "disallowed by robots.txt"},
        {"url": SITE + "docs/boom.pdf", "error": "refused"},
    ]
    assert "GET /pages/cached" not in site
    site.clear()
    assert acquire.acquire_pages([SITE + "pages/one"]) == []
    assert site == []


def test_measuring_sends_only_head_requests(site: list[str]) -> None:
    urls = [SITE + "docs/a.pdf", SITE + "img/unsized.webp", SITE + "docs/gone.pdf"]
    urls += [SITE + "private/c.pdf", SITE + "docs/boom.pdf"]

    results = acquire.measure(urls)

    assert results == [
        {"url": SITE + "docs/a.pdf", "bytes": len(PDF)},
        {"url": SITE + "img/unsized.webp", "bytes": None},  # no content-length
        {"url": SITE + "docs/gone.pdf", "error": "HTTP 404"},
        {"url": SITE + "private/c.pdf", "error": "disallowed by robots.txt"},
        {"url": SITE + "docs/boom.pdf", "error": "refused"},
    ]
    assert all(line.split()[0] in ("GET", "HEAD") for line in site)
    assert [line for line in site if line.startswith("GET")] == ["GET /robots.txt"]


def write_page(name: str, html: str) -> None:
    config.PAGE_CACHE.mkdir(exist_ok=True)
    (config.PAGE_CACHE / f"{name}.html").write_text(html, encoding="utf-8")


def test_links_come_from_every_cached_page_once(site: list[str]) -> None:
    write_page("a", '<a href="/docs/a.pdf">x</a><img src="/img/p.webp">')
    write_page("b", '<a href="/docs/a.pdf">x</a><a href="/docs/b.pdf">y</a>')
    (config.PAGE_CACHE / "sitemap.xml").write_text(
        "<loc>https://example.test/pages/one</loc>", encoding="utf-8"
    )

    assert acquire.cached_links() == (
        [SITE + "docs/a.pdf", SITE + "docs/b.pdf"],
        [SITE + "img/p.webp"],
    )
    assert acquire.sitemap_pages() == [SITE + "pages/one"]


def test_the_command_line_measures_then_collects_pages_and_files(
    site: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    write_page("home", '<a href="/docs/a.pdf">x</a><a href="/docs/gone.pdf">y</a>')
    (config.PAGE_CACHE / "sitemap.xml").write_text(
        f"<loc>{SITE}pages/one</loc><loc>{SITE}pages/moved</loc>", encoding="utf-8"
    )

    assert cli.main(["acquire", "pages", "--measure"]) == 0
    # Sizing follows a redirect, so a moved page counts: an estimate errs high.
    assert capsys.readouterr().out.startswith("2 of 2 fine")
    assert cli.main(["acquire", "pages"]) == 0
    assert (
        "failed: https://example.test/pages/moved: HTTP 301" in capsys.readouterr().out
    )
    assert cli.main(["acquire", "files", "--measure"]) == 0
    assert capsys.readouterr().out.startswith("1 of 2 fine")
    assert cli.main(["acquire", "files"]) == 0
    assert capsys.readouterr().out.startswith(f"1 of 2 fine, {len(PDF) / 1e6:.1f} MB")
    assert cli.main(["acquire", "files", "--measure"]) == 0  # a.pdf is stored now
    assert "gone.pdf: HTTP 404" in capsys.readouterr().out
    assert json.loads((config.FILE_STORE / "manifest.json").read_text())[0]["url"] == (
        SITE + "docs/a.pdf"
    )

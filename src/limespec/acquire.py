"""Collect the openly available sources the knowledge base draws on, politely.

Pages go to the page cache that `limespec ingest` reads. The site's own documents
(PDFs) and images, and the openly licensed external documents listed in
sources-external.txt, go to a content-addressed store: each file once, named by its
SHA-256, with a manifest recording its URL, type, size, licence (for external
documents) and when it was fetched. Every request identifies itself, obeys the
host's robots.txt and waits the polite delay. A failed URL is reported and the
collection goes on; it is tried again next time. `browse` gives the stored files
readable names. Nothing here is committed: data/ is git-ignored.
"""

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from limespec import config
from limespec.ingest import cache_path, load_robots, polite_client

Record = dict[str, Any]  # one URL's outcome, plain JSON-compatible data


def sitemap_urls(xml: str) -> list[str]:
    """Every page URL a sitemap lists, in its order."""
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def is_own(url: str) -> bool:
    """Whether the URL is on the Lime Green site (any of its subdomains)."""
    domain = urlsplit(config.SITE).netloc.removeprefix("www.")
    host = urlsplit(url).netloc
    return host == domain or host.endswith("." + domain)


def linked_files(raw_html: str) -> tuple[list[str], list[str]]:
    """The site's own PDFs and images a page links to, as absolute URLs."""
    soup = BeautifulSoup(raw_html, "html.parser")
    documents = []
    for link in soup.find_all("a", href=True):
        url = urljoin(config.SITE, str(link["href"]).strip())
        if is_own(url) and urlsplit(url).path.lower().endswith(".pdf"):
            documents.append(url)
    images = []
    for image in soup.find_all("img", src=True):
        url = urljoin(config.SITE, str(image["src"]).strip())
        if is_own(url):
            images.append(url)
    return documents, images


def read_external(path: Path) -> dict[str, str]:
    """External documents to collect, each line a URL then its licence."""
    documents = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            url, licence = line.split(maxsplit=1)
            documents[url] = licence.strip()
    return documents


def robots_for(
    client: httpx.Client, url: str, known: dict[str, RobotFileParser]
) -> RobotFileParser:
    """The robots.txt rules of the URL's host, read once per host (then the polite
    delay, as after any request)."""
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}/"
    if root not in known:
        known[root] = load_robots(client, root)
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return known[root]


def store_path(sha256: str) -> Path:
    return config.FILE_STORE / sha256


def read_manifest() -> list[Record]:
    path = config.FILE_STORE / "manifest.json"
    if not path.exists():
        return []
    records: list[Record] = json.loads(path.read_text(encoding="utf-8"))
    return records


def write_manifest(records: list[Record]) -> None:
    config.FILE_STORE.mkdir(parents=True, exist_ok=True)
    text = json.dumps(records, indent=1) + "\n"
    (config.FILE_STORE / "manifest.json").write_text(text, encoding="utf-8")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def fetch_file(
    client: httpx.Client, robots: RobotFileParser, url: str, kind: str
) -> Record:
    """Download one file into the store; its record, or the reason it failed."""
    record: Record = {"url": url, "kind": kind, "fetched_at": now()}
    if not robots.can_fetch(config.USER_AGENT, url):
        return {**record, "error": "disallowed by robots.txt"}
    try:
        response = client.get(url, follow_redirects=True)
    except httpx.HTTPError as error:
        return {**record, "error": str(error)}
    if response.status_code != 200:
        return {**record, "error": f"HTTP {response.status_code}"}
    sha256 = hashlib.sha256(response.content).hexdigest()
    path = store_path(sha256)
    if not path.exists():  # the same bytes under another URL are stored once
        path.write_bytes(response.content)
    return {
        **record,
        "sha256": sha256,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type", ""),
    }


def acquire_files(
    urls: Sequence[str],
    kind: str,
    transport: httpx.BaseTransport | None = None,
    licences: dict[str, str] | None = None,
) -> list[Record]:
    """Download every file not yet in the manifest; return this run's records.

    The manifest keeps successes only and is saved after each file, so a stopped
    run resumes; failures are returned, and retried by the next run. A licence
    given for a URL is kept in its record.
    """
    manifest = read_manifest()
    stored = {record["url"] for record in manifest}
    missing = [url for url in dict.fromkeys(urls) if url not in stored]
    results: list[Record] = []
    if not missing:
        return results
    config.FILE_STORE.mkdir(parents=True, exist_ok=True)
    known: dict[str, RobotFileParser] = {}
    with polite_client(transport) as client:
        for url in missing:
            robots = robots_for(client, url, known)
            record = fetch_file(client, robots, url, kind)
            if licences and url in licences:
                record["licence"] = licences[url]
            time.sleep(config.REQUEST_DELAY_SECONDS)
            results.append(record)
            if "sha256" in record:
                manifest.append(record)
                write_manifest(manifest)
    return results


def acquire_pages(
    urls: Sequence[str], transport: httpx.BaseTransport | None = None
) -> list[Record]:
    """Download every page not yet cached; a failed page is reported, not fatal.

    Redirects are not followed, as for indexed pages: a moved page is reported.
    """
    missing = [url for url in dict.fromkeys(urls) if not cache_path(url).exists()]
    results: list[Record] = []
    if not missing:
        return results
    config.PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    with polite_client(transport) as client:
        robots = load_robots(client)
        for url in missing:
            time.sleep(config.REQUEST_DELAY_SECONDS)
            if not robots.can_fetch(config.USER_AGENT, url):
                results.append({"url": url, "error": "disallowed by robots.txt"})
                continue
            try:
                response = client.get(url)
            except httpx.HTTPError as error:
                results.append({"url": url, "error": str(error)})
                continue
            if response.status_code != 200:
                results.append({"url": url, "error": f"HTTP {response.status_code}"})
                continue
            cache_path(url).write_bytes(response.content)
            results.append({"url": url, "bytes": len(response.content)})
    return results


def measure(
    urls: Sequence[str], transport: httpx.BaseTransport | None = None
) -> list[Record]:
    """Each URL's size from a HEAD request, so a download can be approved first."""
    results: list[Record] = []
    known: dict[str, RobotFileParser] = {}
    with polite_client(transport) as client:
        for url in dict.fromkeys(urls):
            robots = robots_for(client, url, known)
            time.sleep(config.REQUEST_DELAY_SECONDS)
            if not robots.can_fetch(config.USER_AGENT, url):
                results.append({"url": url, "error": "disallowed by robots.txt"})
                continue
            try:
                response = client.head(url, follow_redirects=True)
            except httpx.HTTPError as error:
                results.append({"url": url, "error": str(error)})
                continue
            if response.status_code != 200:
                results.append({"url": url, "error": f"HTTP {response.status_code}"})
                continue
            size = response.headers.get("content-length")
            results.append({"url": url, "bytes": int(size) if size else None})
    return results


def cached_links() -> tuple[list[str], list[str]]:
    """PDFs and images linked from every cached page."""
    documents: list[str] = []
    images: list[str] = []
    for page in sorted(config.PAGE_CACHE.glob("*.html")):
        found = linked_files(page.read_text(encoding="utf-8", errors="replace"))
        documents += found[0]
        images += found[1]
    return list(dict.fromkeys(documents)), list(dict.fromkeys(images))


def sitemap_pages() -> list[str]:
    """The pages the site's cached sitemap lists."""
    path = config.PAGE_CACHE / "sitemap.xml"
    return sitemap_urls(path.read_text(encoding="utf-8"))


def readable_name(record: Record) -> str:
    """The file name the URL ends with, decoded (spaces instead of %20)."""
    return unquote(urlsplit(str(record["url"])).path.rsplit("/", 1)[-1]) or "unnamed"


def browse() -> int:
    """Give every stored file a readable name under data/browse/<kind>/, as a hard
    link (no extra space) or a copy where links are not possible. Two different
    files with the same name get the start of their hash added. Returns how many
    names were made."""
    made = 0
    taken: dict[Path, str] = {}
    for record in read_manifest():
        folder = config.FILE_STORE.parent / "browse" / str(record["kind"])
        name = readable_name(record)
        target = folder / name
        if taken.get(target, record["sha256"]) != record["sha256"]:
            stem, dot, suffix = name.rpartition(".")
            name = (
                f"{stem}-{record['sha256'][:8]}{dot}{suffix}"
                if dot
                else f"{name}-{record['sha256'][:8]}"
            )
            target = folder / name
        taken[target] = str(record["sha256"])
        if target.exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.link(store_path(str(record["sha256"])), target)
        except OSError:
            shutil.copyfile(store_path(str(record["sha256"])), target)
        made += 1
    return made

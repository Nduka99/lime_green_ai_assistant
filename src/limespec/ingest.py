"""Build the local index from the pages listed in sources.txt.

fetch (politely, cached) → extract sections → split long ones → embed → store in SQLite.
Pages are cached in data/site/, so a rebuild never downloads a page twice.
"""

import hashlib
import re
import sqlite3
import textwrap
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from limespec import config
from limespec.retrieve import Embed, to_blob

HEADINGS = ["h1", "h2", "h3", "h4"]
# Some articles style a paragraph as a heading: <p class="h2-style">Application</p>
HEADING_CLASSES = {"h2-style", "h3-style", "h4-style"}
TEXT_BLOCKS = [*HEADINGS, "p", "li", "dt", "dd", "td", "th", "div"]
# Site furniture repeated across pages, found by inspecting the fetched HTML.
BOILERPLATE = ", ".join(
    [
        "header, nav, footer, form, script, style, noscript, svg",
        ".modal",  # login box
        ".maf-bc",  # breadcrumb trail
        ".tabs",  # product tab bar
        ".swatch",  # colour swatches and data-sheet downloads
        ".gal",  # photo gallery
        ".sup-call",  # "Find your nearest supplier" banner
        ".associated",  # related-products cards
        ".blog-highlight",  # related case studies
        ".mblogs",  # "More knowledge base" cards
        ".portal",  # staff profile cards
        ".blog-feed",  # news cards
        ".card-button, .date, .maf-input",  # buttons, dates, pickers
    ]
)
TITLE_BLOCK = ".kb-head"  # a knowledge-base title block: the <h1>, a label, a date
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

SCHEMA = """
CREATE TABLE pages (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sha256 TEXT NOT NULL  -- of the exact cached bytes
);
CREATE TABLE passages (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL REFERENCES pages (url),
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE VIRTUAL TABLE passages_fts USING fts5 (title, text, tokenize = 'porter');
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class IngestError(RuntimeError):
    """A page could not be acquired or read; the message names the URL."""


def read_sources(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def cache_path(url: str) -> Path:
    slug = urlsplit(url).path.strip("/").replace("/", "__") or "home"
    return config.PAGE_CACHE / f"{slug}.html"


def polite_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The one HTTP client for every request: identifying agent, timeout, retries."""
    return httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        transport=transport or httpx.HTTPTransport(retries=config.REQUEST_RETRIES),
    )


def get(
    client: httpx.Client, url: str, follow_redirects: bool = False
) -> httpx.Response:
    try:
        return client.get(url, follow_redirects=follow_redirects)
    except httpx.HTTPError as error:
        raise IngestError(f"{url}: {error}") from error


def fetch_page(client: httpx.Client, url: str) -> bytes:
    response = get(client, url)
    if response.status_code != 200:
        raise IngestError(f"{url}: HTTP {response.status_code}")
    return response.content


def load_robots(client: httpx.Client) -> RobotFileParser:
    """The site's robots.txt rules, following RFC 9309: redirects are followed,
    a 4xx response means no rules (everything allowed), and any other failure
    stops the crawl. Pages, by contrast, never follow redirects: a moved page
    is reported so that sources.txt can be corrected."""
    url = config.SITE + "robots.txt"
    response = get(client, url, follow_redirects=True)
    robots = RobotFileParser(url)
    if response.status_code == 200:
        robots.parse(response.text.splitlines())
    elif 400 <= response.status_code < 500:
        robots.parse([])
    else:
        raise IngestError(f"{url}: HTTP {response.status_code}")
    return robots


def fetch_missing(
    urls: Sequence[str], transport: httpx.BaseTransport | None = None
) -> None:
    """Download every page not yet cached. robots.txt is read first, through the
    same client, and every request is followed by the polite delay."""
    missing = [url for url in urls if not cache_path(url).exists()]
    if not missing:
        return
    config.PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    with polite_client(transport) as client:
        robots = load_robots(client)
        time.sleep(config.REQUEST_DELAY_SECONDS)
        for url in missing:
            if not robots.can_fetch(config.USER_AGENT, url):
                raise IngestError(f"{url}: disallowed by robots.txt")
            cache_path(url).write_bytes(fetch_page(client, url))
            time.sleep(config.REQUEST_DELAY_SECONDS)


def clean(text: str) -> str:
    return " ".join(text.split())


def extract_sections(raw_html: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Return the page title and its (heading, paragraphs) sections in reading order.

    Headings start sections; each FAQ question (<dt>) starts one, so every
    question and its answer stay together. Only leaf blocks are read, so no
    text is counted twice, and inline tags such as links join without a space.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    for line_break in soup.find_all("br"):
        line_break.replace_with(" ")
    root = soup.find("main") or soup.body  # six category pages have no <main>
    if root is None:
        raise ValueError("page has no <body>")
    for element in root.select(BOILERPLATE):
        element.decompose()
    # Read the title after the header is gone (its menu cards use <h1> too) and
    # before the title block is removed (it holds the article's <h1>).
    title_tag = root.find("h1") or soup.title
    title = clean(title_tag.get_text()) if title_tag else ""
    for element in root.select(TITLE_BLOCK):
        element.decompose()

    sections: list[tuple[str, list[str]]] = []
    heading = title
    paragraphs: list[str] = []
    for block in root.find_all(TEXT_BLOCKS):
        if block.find(TEXT_BLOCKS):
            continue
        text = clean(block.get_text())
        if not text:
            continue
        is_heading = block.name in HEADINGS or bool(
            HEADING_CLASSES & set(block.get("class") or [])
        )
        if is_heading or block.name == "dt":
            if paragraphs:
                sections.append((heading, paragraphs))
            heading, paragraphs = text, []
        else:
            paragraphs.append(text)
    if paragraphs:
        sections.append((heading, paragraphs))
    return title, sections


def pieces(paragraph: str, budget: int) -> list[str]:
    """A paragraph that fits the budget stays whole; a longer one is split at
    sentence ends, and a sentence that is still too long at spaces. Words and
    hyphenated words are never broken, so every quote survives unchanged."""
    if len(paragraph) <= budget:
        return [paragraph]
    parts: list[str] = []
    for sentence in SENTENCE_END.split(paragraph):
        if len(sentence) <= budget:
            parts.append(sentence)
        else:
            parts += textwrap.wrap(
                sentence, budget, break_long_words=False, break_on_hyphens=False
            )
    return parts


def split_section(heading: str, paragraphs: list[str]) -> list[str]:
    """Passage texts for one section: the heading, then as many paragraph pieces
    as fit in MAX_PASSAGE_CHARS. Every passage stays within the maximum."""
    budget = config.MAX_PASSAGE_CHARS - len(heading) - 1
    passages: list[list[str]] = [[]]
    for paragraph in paragraphs:
        for piece in pieces(paragraph, budget):
            candidate = "\n".join([heading, *passages[-1], piece])
            if passages[-1] and len(candidate) > config.MAX_PASSAGE_CHARS:
                passages.append([])
            passages[-1].append(piece)
    return ["\n".join([heading, *chunk]) for chunk in passages]


def page_passages(raw_html: str) -> tuple[str, list[tuple[str, str]]]:
    """The page title and its (heading, text) passages, each text once per page."""
    title, sections = extract_sections(raw_html)
    passages: list[tuple[str, str]] = []
    seen: set[str] = set()
    for heading, paragraphs in sections:
        for text in split_section(heading, paragraphs):
            key = clean(text).casefold()
            if key not in seen:
                seen.add(key)
                passages.append((heading, text))
    return title, passages


def corpus_hash(page_hashes: Sequence[tuple[str, str]]) -> str:
    """One fingerprint for the whole corpus, from sorted (url, sha256) pairs."""
    lines = "".join(f"{url} {sha256}\n" for url, sha256 in sorted(page_hashes))
    return hashlib.sha256(lines.encode()).hexdigest()


def build_index(
    database: Path, pages: Sequence[tuple[str, bytes, str]], embed: Embed
) -> dict[str, str]:
    """Rebuild the index from (url, raw_bytes, fetched_at) pages; return its manifest.

    The new index is written beside the old one and swapped in only when
    complete, so a failed rebuild leaves the previous index untouched.
    """
    page_rows: list[tuple[str, str, str, str]] = []  # url, title, fetched_at, sha256
    rows: list[tuple[str, str, str, str]] = []  # url, title, heading, text
    for url, raw, fetched_at in pages:
        try:
            title, passages = page_passages(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise IngestError(f"{url}: {error}") from error
        page_rows.append((url, title, fetched_at, hashlib.sha256(raw).hexdigest()))
        rows += [(url, title, heading, text) for heading, text in passages]

    vectors: list[list[float]] = []
    for start in range(0, len(rows), config.EMBEDDING_BATCH_SIZE):
        batch = rows[start : start + config.EMBEDDING_BATCH_SIZE]
        vectors += embed([f"{title}\n{text}" for _, title, _, text in batch])

    # The site stamps each response with its render time, so page bytes (and the
    # corpus hash) change on every download; the passage hash changes only when
    # the indexed text does, which makes it the fingerprint for comparing builds.
    passage_lines = "".join(f"{url}\t{text}\n" for url, _, _, text in rows)
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus_sha256": corpus_hash([(row[0], row[3]) for row in page_rows]),
        "passages_sha256": hashlib.sha256(passage_lines.encode()).hexdigest(),
        "embedding_model": config.EMBEDDING_MODEL,
        "pages": str(len(page_rows)),
        "passages": str(len(rows)),
    }
    database.parent.mkdir(parents=True, exist_ok=True)
    building = database.with_suffix(".building")
    building.unlink(missing_ok=True)
    conn = sqlite3.connect(building)
    try:
        with conn:  # one transaction: commits on success, rolls back on error
            conn.executescript(SCHEMA)
            conn.executemany("INSERT INTO pages VALUES (?, ?, ?, ?)", page_rows)
            for passage_id, ((url, title, heading, text), vector) in enumerate(
                zip(rows, vectors, strict=True), start=1
            ):
                conn.execute(
                    "INSERT INTO passages VALUES (?, ?, ?, ?, ?)",
                    (passage_id, url, heading, text, to_blob(vector)),
                )
                conn.execute(
                    "INSERT INTO passages_fts (rowid, title, text) VALUES (?, ?, ?)",
                    (passage_id, title, text),
                )
            conn.executemany("INSERT INTO meta VALUES (?, ?)", manifest.items())
    finally:
        conn.close()
    building.replace(database)
    return manifest


def fetched_at(path: Path) -> str:
    """The cache file's modification time is when the page was captured."""
    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return modified.isoformat(timespec="seconds")


def ingest(
    embed: Embed, sources: Path | None = None, database: Path | None = None
) -> dict[str, str]:
    urls = read_sources(sources or config.SOURCES_FILE)
    fetch_missing(urls)
    pages = [
        (url, cache_path(url).read_bytes(), fetched_at(cache_path(url))) for url in urls
    ]
    return build_index(database or config.DATABASE, pages, embed)

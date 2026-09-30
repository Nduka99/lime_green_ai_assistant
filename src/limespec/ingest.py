"""Build the index from the pages listed in sources.txt.

fetch (politely, cached) → extract sections → split long ones → embed → store in
Postgres as a new live index version. Pages are cached in data/site/, so a rebuild
never downloads a page twice.
"""

import hashlib
import posixpath
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

from limespec import config, lists, prices, store
from limespec.models import described
from limespec.passages import pieces
from limespec.retrieve import Embed

HEADINGS = ["h1", "h2", "h3", "h4"]
# Some articles style a paragraph as a heading: <p class="h2-style">Application</p>
HEADING_CLASSES = {"h2-style", "h3-style", "h4-style"}
TEXT_BLOCKS = [*HEADINGS, "p", "li", "dt", "dd", "td", "th", "div"]
# Articles set a sub-heading, an interview question or a list's lead-in as a wholly
# bold paragraph. Such a line is at most this long and does not end like a sentence
# of the running text (147 on 56 of the site's 160 pages, E5).
BOLD_LINE_CHARS = 200
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


class IngestError(RuntimeError):
    """Ingestion cannot run: a page could not be acquired or read (the message names
    its URL), or the Postgres target is not configured."""


def read_sources(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def cache_path(url: str) -> Path:
    slug = urlsplit(url).path.strip("/").replace("/", "__") or "home"
    return config.PAGE_CACHE / f"{slug}.html"


def page_url(slug: str) -> str:
    """A cached page's address, rebuilt from its file name (`cache_path` reversed)."""
    return config.SITE if slug == "home" else config.SITE + slug.replace("__", "/")


def site_pages() -> list[str]:
    """The address of every cached page of the site."""
    return [page_url(path.stem) for path in sorted(config.PAGE_CACHE.glob("*.html"))]


def file_links(raw_html: str) -> list[tuple[str, str, str]]:
    """(kind, absolute URL, link or alt text) for every PDF and image a page links."""
    soup = BeautifulSoup(raw_html, "html.parser")
    found = []
    for link in soup.find_all("a", href=True):
        url = urljoin(config.SITE, str(link["href"]).strip())
        if urlsplit(url).path.lower().endswith(".pdf"):
            found.append(("document", url, " ".join(link.get_text(" ").split())))
    for image in soup.find_all("img", src=True):
        url = urljoin(config.SITE, str(image["src"]).strip())
        found.append(("image", url, str(image.get("alt", "")).strip()))
    return found


def site_html() -> list[tuple[str, str]]:
    """(URL, HTML) for every cached page of the site."""
    pages = []
    for url in site_pages():
        pages.append((url, cache_path(url).read_text(encoding="utf-8")))
    return pages


def file_title(url: str) -> str:
    """A document's file name without its extension ("Hemp binder TDS")."""
    name = unquote(posixpath.basename(urlsplit(url).path))
    return posixpath.splitext(name)[0]


def pdf_titles(pages: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Each linked PDF's title from (page URL, HTML) pages: the title of a product
    page linking it (else the first page that does) and the site's own link text,
    as in "Warmshell Aerogel — SDS"."""
    titles: dict[str, str] = {}
    for _, raw in sorted(pages, key=lambda page: "/products/" not in page[0]):
        title, _ = extract_sections(raw)
        for kind, link, text in file_links(raw):
            if kind == "document" and link not in titles:
                titles[link] = f"{title} — {text}" if text else title
    return titles


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


def load_robots(client: httpx.Client, site: str = "") -> RobotFileParser:
    """A site's robots.txt rules (the Lime Green site's unless `site` is given),
    following RFC 9309: redirects are followed, a 4xx response means no rules
    (everything allowed), and any other failure stops the crawl. Pages, by
    contrast, never follow redirects: a moved page is reported so that
    sources.txt can be corrected."""
    url = (site or config.SITE) + "robots.txt"
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


def bold_line(block: Tag, text: str) -> bool:
    """Whether a paragraph is a bold line: every word in <strong> or <b>, short, and
    not ending in a full stop or an exclamation mark."""
    if block.name != "p" or len(text) > BOLD_LINE_CHARS or text[-1] in ".!":
        return False
    words = [string for string in block.find_all(string=True) if string.strip()]
    return all(string.find_parent(["strong", "b"]) for string in words)


def extract_sections(raw_html: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Return the page title and its (heading, paragraphs) sections in reading order.

    Headings start sections; each FAQ question (<dt>) starts one, so every
    question and its answer stay together. A bold line starts a new section under
    the same heading, as its first paragraph, so a list or an answer stays with the
    line that introduces it. A list is one paragraph, its items on separate lines
    after the lead-in that ends with a colon, so the splitter keeps it whole. Only
    leaf blocks are read, so no text is counted twice, and inline tags such as links
    join without a space.
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
    open_list: Tag | None = None  # the list the paragraph before belongs to
    for block in root.find_all(TEXT_BLOCKS):
        if block.find(TEXT_BLOCKS):
            continue
        text = clean(block.get_text())
        if not text:
            continue
        is_heading = block.name in HEADINGS or bool(
            HEADING_CLASSES & set(block.get("class") or [])
        )
        # The block's list: an item, or a paragraph inside an item.
        item = block if block.name == "li" else block.find_parent("li")
        this_list = item.find_parent(["ul", "ol"]) if item else None
        if is_heading or block.name == "dt":
            if paragraphs:
                sections.append((heading, paragraphs))
            heading, paragraphs = text, []
        elif paragraphs and bold_line(block, text):
            sections.append((heading, paragraphs))
            paragraphs = [text]
        elif (
            paragraphs
            and this_list is not None
            and (
                this_list is open_list
                or (open_list is None and paragraphs[-1].endswith(":"))
            )
        ):
            paragraphs[-1] += "\n" + text  # the list's next item, or its first
        else:
            paragraphs.append(text)
        open_list = this_list
    if paragraphs:
        sections.append((heading, paragraphs))
    return title, sections


def split_section(heading: str, paragraphs: list[str]) -> list[str]:
    """Passage texts for one section: the heading, then as many paragraph pieces
    as fit in MAX_PASSAGE_CHARS. Every passage stays within the maximum. A list
    (a paragraph of several lines) stays whole when it fits in a passage; a longer
    one is split between its items."""
    budget = config.MAX_PASSAGE_CHARS - len(heading) - 1
    passages: list[list[str]] = [[]]
    for paragraph in paragraphs:
        lines = paragraph.split("\n") if len(paragraph) > budget else [paragraph]
        for line in lines:
            for piece in pieces(line, budget):
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


@dataclass(frozen=True)
class PreparedIndex:
    """Everything one index version holds, ready to be written to Postgres."""

    pages: list[store.PageRow]  # url, title, fetched_at, sha256
    passages: list[store.PassageRow]  # url, title, heading, text, context, page
    vectors: list[list[float]]  # one per passage
    manifest: dict[str, str]


def fingerprint_line(row: store.PassageRow) -> str:
    """A passage as the fingerprint counts it: a web passage by its URL and text (as
    every earlier version), a PDF passage also by its page and context."""
    url, _, _, text, context, page = row
    if page is None and not context:
        return f"{url}\t{text}\n"
    return f"{url}\t{page}\t{context}\t{text}\n"


def without_prices(row: store.PassageRow) -> store.PassageRow | None:
    """The passage without its sentences that state a price (`prices`), or None when
    nothing but its heading is left. A passage with no price is returned as it is."""
    url, title, heading, text, context, page = row
    kept = prices.without_prices(text)
    if kept != text and kept.strip() in ("", heading.strip()):
        return None
    return (url, title, heading, kept, context, page)


def prepare_index(
    pages: Sequence[tuple[str, bytes, str]],
    embed: Embed,
    documents: Sequence[tuple[store.PageRow, list[store.PassageRow]]] = (),
) -> PreparedIndex:
    """Parse, embed and fingerprint (url, raw_bytes, fetched_at) pages, and add
    documents whose passages are already built (PDFs, limespec.passages)."""
    page_rows: list[store.PageRow] = []
    rows: list[store.PassageRow] = []
    for url, raw, fetched_at in pages:
        try:
            title, passages = page_passages(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise IngestError(f"{url}: {error}") from error
        page_rows.append((url, title, fetched_at, hashlib.sha256(raw).hexdigest()))
        rows += [(url, title, heading, text, "", None) for heading, text in passages]
        # A product grid also becomes one passage holding its whole list (X12).
        products = lists.grid_products(raw.decode("utf-8"))
        if products:
            compiled = lists.list_passage(title, products)
            rows.append((url, title, lists.HEADING, compiled, "", None))
    for page_row, passage_rows in documents:
        page_rows.append(page_row)
        rows += passage_rows
    rows = [row for row in map(without_prices, rows) if row is not None]

    vectors: list[list[float]] = []
    for start in range(0, len(rows), config.EMBEDDING_BATCH_SIZE):
        batch = rows[start : start + config.EMBEDDING_BATCH_SIZE]
        vectors += embed([described(row[1], row[4], row[3]) for row in batch])

    # The site stamps each response with its render time, so page bytes (and the
    # corpus hash) change on every download; the passage hash changes only when
    # the indexed text does, which makes it the fingerprint for comparing builds.
    passage_lines = "".join(fingerprint_line(row) for row in rows)
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus_sha256": corpus_hash([(row[0], row[3]) for row in page_rows]),
        "passages_sha256": hashlib.sha256(passage_lines.encode()).hexdigest(),
        "embedding_model": config.EMBEDDING_MODEL,
        "pages": str(len(page_rows)),
        "passages": str(len(rows)),
    }
    return PreparedIndex(page_rows, rows, vectors, manifest)


def fetched_at(path: Path) -> str:
    """The cache file's modification time is when the page was captured."""
    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return modified.isoformat(timespec="seconds")


def cached_pages(urls: Sequence[str]) -> list[tuple[str, bytes, str]]:
    """(url, raw_bytes, fetched_at) for every source, downloading the missing ones."""
    fetch_missing(urls)
    pages = []
    for url in urls:
        path = cache_path(url)
        pages.append((url, path.read_bytes(), fetched_at(path)))
    return pages


def ingest(
    conn: store.Connection,
    embed: Embed,
    sources: Path | None = None,
    live: bool = True,
    all_pages: bool = False,
    documents: Sequence[tuple[store.PageRow, list[store.PassageRow]]] = (),
) -> tuple[int, dict[str, str]]:
    """Build a new Postgres index version from the sources and, unless `live` is
    False, make it live. `all_pages` takes every cached page of the site instead of
    the sources; `documents` are added with their passages already built (PDFs,
    `documents.index_documents`).

    The version is written beside the live one and switched in a single
    transaction, so a failed build leaves the served index untouched. A version
    left not live can be evaluated first (`LIMESPEC_INDEX_VERSION`).
    """
    urls = site_pages() if all_pages else read_sources(sources or config.SOURCES_FILE)
    prepared = prepare_index(cached_pages(urls), embed, documents)
    version = store.write_version(
        conn, prepared.pages, prepared.passages, prepared.vectors, prepared.manifest
    )
    if live:
        store.set_live(conn, version)
    return version, prepared.manifest

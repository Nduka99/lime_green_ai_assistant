"""Label every collected source by format and topic: the strata a key samples from.

A format comes from where a source sits and how the site itself links to it (a PDF
linked as "SDS" is a safety data sheet); a topic comes from the product family of
the page it belongs to. Every label is a rule a reader can check, not a model's
guess. Keys are then sampled with equal allocation across formats, and results are
reported per stratum (Coverage, Not Averages, 2026).
"""

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import unquote, urlsplit

from limespec import acquire, config, ingest

Entry = dict[str, Any]  # one source: plain JSON-compatible data
# The site's product families (products/<family>/...), plus Warmshell insulation.
PRODUCT_FAMILIES = {
    "insulation", "lime-mortar", "lime-plaster", "lime-render",
    "primers-and-adhesives", "stone-repair",
}  # fmt: skip

WORD = re.compile(r"\w+")
TEXT_WORDS = 3  # words read in a picture: fewer, and it is a visual-only picture

# First match wins, on the site's link text, then on the file name.
PDF_FORMATS = [
    ("pdf:safety", r"\b(sds|msds|safety)\b"),
    ("pdf:performance", r"\b(dop|doc|declaration|epd|carbon|lrv)\b"),
    ("pdf:technical", r"\b(data ?sheet|tds|technical)\b"),
    (
        "pdf:guide",
        r"\b(guide|installation|system information|repair|history|checklist"
        r"|specification|reference|drawing)",
    ),
    ("pdf:certificate", r"(baw-|agr[eé]ment|certificate|iso\d|classification)"),
    ("pdf:policy", r"(terms|return|brochure|warranty)"),
]


def page_format(slug: str) -> str:
    """A cached page's format, from its URL path (the cache file's name)."""
    section = slug.split("__")[0]
    if section in ("products", "warmshell-natural-insulation"):
        return "page:product"
    if section == "products-by-colour":
        return "page:colour"
    if slug.startswith("support__case-studies"):
        return "page:case-study"
    if slug.startswith(("support__knowledgebase", "support__faq")):
        return "page:knowledge"
    if section in ("news", "inspirations"):
        return "page:news"
    return "page:company"


def page_topic(slug: str) -> str:
    """A cached page's topic: its product family, or what else it is about."""
    parts = slug.split("__")
    if parts[0] == "products" and len(parts) > 1:
        return parts[1]
    if parts[0] == "warmshell-natural-insulation":
        return "insulation"
    if parts[0] == "products-by-colour":
        return "colours"
    if slug.startswith("support__case-studies"):
        return "case-studies"
    if slug.startswith("support__knowledgebase"):
        return "building-science"
    if slug.startswith("support__faq"):
        return "faq"
    if parts[0] in ("news", "inspirations"):
        return "news"
    return "company"


def pdf_format(link_texts: list[str], url: str) -> str:
    """A PDF's format from how the site links to it, else from its decoded file
    name ("IWI%20Architect%20Reference" must read as words)."""
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    for text in [*link_texts, name]:
        for label, pattern in PDF_FORMATS:
            if re.search(pattern, text, re.IGNORECASE):
                return label
    return "pdf:other"


def file_topic(page_topics: list[str]) -> str:
    """A file's topic from the pages linking to it: a product family if any product
    page links it (a datasheet belongs to its product), else the first page's."""
    for topic in page_topics:
        if topic in PRODUCT_FAMILIES:
            return topic
    return page_topics[0] if page_topics else "unknown"


def catalogue() -> list[Entry]:
    """Every cached page and every stored file, labelled; a file takes its topic
    from the pages that link to it (`file_topic`) and lists those pages."""
    entries: list[Entry] = []
    link_texts: dict[str, list[str]] = {}
    linked_topics: dict[str, list[str]] = {}
    linking_pages: dict[str, list[str]] = {}
    for page in sorted(config.PAGE_CACHE.glob("*.html")):
        slug = page.stem
        entries.append(
            {
                "id": f"page:{slug}",
                "format": page_format(slug),
                "topic": page_topic(slug),
                "source": str(page),
                "url": ingest.page_url(slug),
            }
        )
        raw = page.read_text(encoding="utf-8", errors="replace")
        for _, url, text in ingest.file_links(raw):
            link_texts.setdefault(url, []).append(text)
            linked_topics.setdefault(url, []).append(page_topic(slug))
            linking_pages.setdefault(url, []).append(f"page:{slug}")
    for record in acquire.read_manifest():
        url = str(record["url"])
        texts = link_texts.get(url, [])
        if record["kind"] == "external":
            fmt, topic = "external:guidance", "regulation"
        elif url.lower().endswith(".docx"):
            fmt, topic = "docx:declaration", file_topic(linked_topics.get(url, []))
        elif record["kind"] == "image":
            fmt, topic = "image", file_topic(linked_topics.get(url, []))
        else:
            fmt, topic = pdf_format(texts, url), file_topic(linked_topics.get(url, []))
        entries.append(
            {
                "id": f"file:{record['sha256']}",
                "format": fmt,
                "topic": topic,
                "source": str(acquire.store_path(str(record["sha256"]))),
                "url": url,
                "text": next((t for t in texts if t), ""),
                "pages": sorted(set(linking_pages.get(url, []))),
            }
        )
    return unique(entries) + pictures(entries)


def pictures(entries: list[Entry]) -> list[Entry]:
    """Every stored picture (`limespec read-images`), once: filed where its alt text
    says most about it, its topic that place's, and `pages` the sources showing it
    (so a picture joins its page's subject). A picture holds text when a machine
    read TEXT_WORDS or more words in it (X43 B2), else it is visual only."""
    places_file = config.IMAGES / "places.json"
    if not places_file.exists():
        return []
    topics = {entry["url"]: entry["topic"] for entry in entries}
    ids = {entry["url"]: entry["id"] for entry in entries}
    chosen: dict[str, Entry] = {}
    shown_on: dict[str, set[str]] = {}
    for place in json.loads(places_file.read_text(encoding="utf-8")):
        best = chosen.get(place["id"])
        if best is None or len(place["alt"]) > len(best["alt"]):
            chosen[place["id"]] = place
        if place["source"] in ids:
            shown_on.setdefault(place["id"], set()).add(ids[place["source"]])
    found = []
    for identity, place in chosen.items():
        reading = config.IMAGES / f"{identity}.json"
        read = (
            json.loads(reading.read_text(encoding="utf-8"))["ocr"]
            if reading.exists()
            else ""
        )
        holds_text = len(WORD.findall(read)) >= TEXT_WORDS
        found.append(
            {
                "id": f"picture:{identity}",
                "format": "image:text" if holds_text else "image:visual",
                "topic": topics.get(place["source"], "company"),
                "source": str(config.IMAGES / f"{identity}.png"),
                "url": place["source"],
                "page": place["page"],
                "alt": place["alt"],
                "read": read,
                "pages": sorted(shown_on.get(identity, set())),
            }
        )
    return found


def unique(entries: list[Entry]) -> list[Entry]:
    """One entry per source: the same stored file under several URLs counts once."""
    seen: dict[str, Entry] = {}
    for entry in entries:
        seen.setdefault(entry["id"], entry)
    return list(seen.values())


def strata(entries: list[Entry]) -> dict[str, int]:
    """How many sources each format holds."""
    return dict(sorted(Counter(entry["format"] for entry in entries).items()))

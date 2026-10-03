"""Pages for experiment X8, drawn by code before any parser reads them.

Per format, the catalogue's documents are sorted by id and shuffled by one seeded
generator. Each document gives its first page with a text layer (declarations and
datasheets, whose first page holds their tables) or a seeded random one (the rest).
With seed 8 and the document probed in S0 excluded, this reproduces round 1's twenty
pages exactly. Round 2 also leaves out round 1's documents and any page resembling
an earlier one, and takes further pages from its documents when a format has fewer
new documents than its quota.
"""

import random
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError

from evaluation.catalogue import Entry

# (format, pages, which page each document gives): round 1's quotas.
QUOTAS = (
    ("pdf:performance", 5, "first"),
    ("pdf:technical", 5, "first"),
    ("pdf:safety", 3, "random"),
    ("pdf:guide", 5, "random"),
    ("pdf:policy", 1, "random"),
    ("pdf:certificate", 1, "random"),
)
# A page with fewer words is a cover or a drawing rather than running text; this is
# the rule that reproduces round 1 (checked on 28 September 2026).
MIN_WORDS = 10
# Word-set resemblance at which two pages count as the same page (near-duplicates,
# such as the UK and EU declarations of one product).
NEAR_DUPLICATE = 0.8

ReadPages = Callable[[str], list[str]]  # a document's file → each page's text layer


def read_pages(source: str) -> list[str]:
    """Each page's text layer; none for a file pypdf cannot read (AES encryption
    needs pypdf's cryptography extra)."""
    try:
        return [page.extract_text() or "" for page in PdfReader(Path(source)).pages]
    except (PyPdfError, DependencyError, ValueError):
        return []


def text_pages(texts: list[str]) -> list[int]:
    """Numbers (from 1) of the pages whose text layer holds at least MIN_WORDS words."""
    return [n for n, text in enumerate(texts, 1) if len(text.split()) >= MIN_WORDS]


def resemblance(first: str, second: str) -> float:
    """The share of words two texts have in common (Jaccard, over word sets)."""
    a = set(first.casefold().split())
    b = set(second.casefold().split())
    return len(a & b) / len(a | b) if a | b else 1.0


def sample(
    entries: list[Entry],
    read: ReadPages,
    seed: int,
    exclude: Iterable[str] = (),
    seen: Iterable[str] = (),
    near: float = NEAR_DUPLICATE,
) -> list[dict[str, Any]]:
    """The sampled pages in quota order. `exclude` names documents never to use, and
    `seen` holds the text of pages used before; a page resembling one of those or an
    earlier sampled page at `near` or more is passed over."""
    rng = random.Random(seed)
    skipped = set(exclude)
    earlier = list(seen)
    chosen: list[dict[str, Any]] = []
    for form, quota, rule in QUOTAS:
        documents = sorted((e for e in entries if e["format"] == form), key=_id)
        rng.shuffle(documents)
        documents = [entry for entry in documents if entry["id"] not in skipped]
        drawn: dict[str, set[int]] = {}
        count = 0
        # One page per document in each pass; a later pass gives another page of
        # each document, until the quota is met or no page is left.
        tried = True
        while count < quota and tried:
            tried = False
            for entry in documents:
                if count == quota:
                    break
                texts = read(entry["source"])
                used = drawn.setdefault(entry["id"], set())
                pages = [page for page in text_pages(texts) if page not in used]
                if not pages:
                    continue
                tried = True
                page = pages[0] if rule == "first" else rng.choice(pages)
                used.add(page)
                text = texts[page - 1]
                if any(resemblance(text, other) >= near for other in earlier):
                    continue
                earlier.append(text)
                chosen.append(_page(entry, page))
                count += 1
    return chosen


def candidates(
    entries: list[Entry],
    read: ReadPages,
    seed: int,
    used: set[tuple[str, int]],
    seen: Iterable[str] = (),
    per_document: int = 2,
    near: float = NEAR_DUPLICATE,
) -> list[dict[str, Any]]:
    """Every PDF page with a text layer, in a seeded order, that no earlier round
    `used`, that resembles no earlier page, and that is not beyond `per_document`
    pages of one document: the candidates from which round 3 takes the first pages
    whose image shows a table."""
    pdfs = sorted((e for e in entries if e["format"].startswith("pdf:")), key=_id)
    pages = [(entry, n) for entry in pdfs for n in text_pages(read(entry["source"]))]
    random.Random(seed).shuffle(pages)
    earlier = list(seen)
    taken: dict[str, int] = {}
    chosen = []
    for entry, number in pages:
        if (entry["id"], number) in used or taken.get(entry["id"], 0) == per_document:
            continue
        text = read(entry["source"])[number - 1]
        if any(resemblance(text, other) >= near for other in earlier):
            continue
        earlier.append(text)
        taken[entry["id"]] = taken.get(entry["id"], 0) + 1
        chosen.append(_page(entry, number))
    return chosen


def blank(
    entries: list[Entry], read: ReadPages, seed: int, count: int
) -> list[dict[str, Any]]:
    """`count` of the PDF pages without a text layer (fewer than MIN_WORDS words:
    drawings, scans, covers), drawn by a seeded generator, for the transcription
    check."""
    pdfs = sorted((e for e in entries if e["format"].startswith("pdf:")), key=_id)
    pages = []
    for entry in pdfs:
        texts = read(entry["source"])
        have = set(text_pages(texts))
        pages += [_page(entry, n) for n in range(1, len(texts) + 1) if n not in have]
    return random.Random(seed).sample(pages, min(count, len(pages)))


def _id(entry: Entry) -> str:
    return str(entry["id"])


def _page(entry: Entry, page: int) -> dict[str, Any]:
    return {
        "format": entry["format"],
        "entry": entry["id"],
        "url": entry["url"],
        "page": page,
        "source": entry["source"],
    }

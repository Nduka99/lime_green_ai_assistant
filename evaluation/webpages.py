"""X42: web pages measured against what they show.

The audit (W0) compares each cached page's main content, after the site furniture is
removed, with what the extractor keeps, and describes the passages it makes. The sample
(W1) draws the pages whose ground truth is judged from their rendering.
"""

import random
from collections import Counter
from collections.abc import Mapping
from typing import Any

from bs4 import BeautifulSoup, Tag

from limespec import ingest

LEVELS = ["h1", "h2", "h3", "h4", "h5", "h6"]
TINY = 120  # characters below a passage's heading: a passage this short holds little
REPEAT = 40  # shorter bodies ("Find a supplier") are not counted as repeated text
RICH = 8  # structure-rich pages drawn first
QUOTAS = {"product": 8, "colour": 4, "knowledge": 6, "case study": 4, "news": 3}
OTHER = 5


def page_type(slug: str) -> str:
    """A cached page's type, from its file name (`ingest.cache_path`)."""
    parts = slug.split("__")
    if parts[0] == "products" and len(parts) == 3:
        return "product"
    if parts[0] == "warmshell-natural-insulation" and len(parts) == 2:
        return "product"
    if parts[0] == "products-by-colour" and len(parts) == 2:
        return "colour"
    if parts[:2] == ["support", "knowledgebase"] or parts[0] == "inspirations":
        return "knowledge" if len(parts) > 1 else "other"
    if parts[:2] == ["support", "case-studies"] and len(parts) == 3:
        return "case study"
    if parts[0] == "news" and len(parts) == 2:
        return "news"
    return "other"


def main_content(raw: str) -> Tag:
    """The page's main content as a visitor sees it, the site furniture removed (the
    title block stays: its title, label and date are shown)."""
    soup = BeautifulSoup(raw, "html.parser")
    for line_break in soup.find_all("br"):
        line_break.replace_with(" ")
    root = soup.find("main") or soup.body or soup
    for element in root.select(ingest.BOILERPLATE):
        element.decompose()
    return root


def words(text: str) -> Counter[str]:
    return Counter(word.casefold() for word in text.split())


def structure_rich(raw: str) -> bool:
    """Nested headings, a definition list or a table in the main content."""
    root = main_content(raw)
    levels = {tag.name for tag in root.find_all(LEVELS[1:])}
    return len(levels) >= 2 or root.find(["dl", "table"]) is not None


def audit_page(raw: str) -> dict[str, Any]:
    """One page: words shown but not extracted, heading levels, and its passages'
    bodies. (Words the extractor adds are not counted here: as a bag of words they
    mix glued words with the title repeated as the first section's heading; W2
    measures precision against the ground truth.)"""
    title, sections = ingest.extract_sections(raw)
    shown = words(main_content(raw).get_text(" "))
    kept = words(" ".join([title] + [h + " " + " ".join(p) for h, p in sections]))
    _, passages = ingest.page_passages(raw)
    bodies = [text[len(heading) :].strip() for heading, text in passages]
    levels = sorted({tag.name for tag in main_content(raw).find_all(LEVELS)})
    return {
        "words": sum(shown.values()),
        "lost": sum((shown - kept).values()),
        "levels": levels,
        "passages": len(bodies),
        "tiny": sum(len(body) < TINY for body in bodies),
        "bodies": bodies,
    }


def audit(pages: Mapping[str, str]) -> dict[str, Any]:
    """Every page (by cache slug) and the totals, with bodies repeated across pages."""
    rows = {slug: audit_page(raw) for slug, raw in pages.items()}
    where: dict[str, set[str]] = {}
    for slug, row in rows.items():
        for body in row["bodies"]:
            key = " ".join(body.split()).casefold()
            if len(key) > REPEAT:
                where.setdefault(key, set()).add(slug)
    for row in rows.values():
        row["repeated"] = sum(
            len(where.get(" ".join(b.split()).casefold(), ())) > 1
            for b in row["bodies"]
        )
        del row["bodies"]
    total = {
        name: sum(row[name] for row in rows.values())
        for name in ("words", "lost", "passages", "tiny", "repeated")
    }
    total["nested"] = sum(len(set(r["levels"]) - {"h1"}) >= 2 for r in rows.values())
    return {"pages": rows, "total": total}


def sample(pages: Mapping[str, str], seed: int) -> list[str]:
    """W1's pages: RICH structure-rich pages, then each type to its quota."""
    rng = random.Random(seed)
    rich = sorted(slug for slug, raw in pages.items() if structure_rich(raw))
    chosen = rng.sample(rich, min(RICH, len(rich)))
    for kind, quota in [*QUOTAS.items(), ("other", OTHER)]:
        have = sum(page_type(slug) == kind for slug in chosen)
        pool = sorted(s for s in pages if page_type(s) == kind and s not in chosen)
        chosen += rng.sample(pool, max(0, min(quota - have, len(pool))))
    return chosen

"""X42: web pages measured against what they show.

The audit (W0) compares each cached page's main content, after the site furniture is
removed, with what the extractor keeps, and describes the passages it makes. The sample
(W1) draws the pages whose ground truth is judged from their rendering: each cached
page drawn by headless Chromium with the site's own CSS, fonts and images, third-party
requests blocked, kept as a full-page screenshot and its visible text.
"""

import random
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from limespec import config, ingest

LEVELS = ["h1", "h2", "h3", "h4", "h5", "h6"]
VIEWPORT = {"width": 1280, "height": 900}
# Trackers and embedded widgets (analytics, reCAPTCHA, video, the NBS spec widget):
# not part of the page a visitor reads, and not to be contacted.
BLOCKED = (
    "googletagmanager.com",
    "google-analytics.com",
    "google.com",
    "doubleclick.net",
    "youtube.com",
    "youtube-nocookie.com",
    "thenbs.com",
)
CONSENT = "Essential only"  # the site's cookie notice: the least a visitor accepts
SETTLE_MS = 150  # after each scroll step, for scroll-triggered animations
OPEN_MS = 400  # after each click on an accordion term, for its slide animation
TINY = 120  # characters below a passage's heading: a passage this short holds little
REPEAT = 40  # shorter bodies ("Find a supplier") are not counted as repeated text
RICH = 8  # structure-rich pages drawn first
QUOTAS = {"product": 8, "colour": 4, "knowledge": 6, "case study": 4, "news": 3}
OTHER = 5
HELD_OUT = {"product": 3, "colour": 1, "knowledge": 2, "case study": 1, "news": 1}
HELD_OUT_OTHER = 2
ARMS = ("current", "docling", "trafilatura")
WORD = re.compile(r"\w+")
BLANK_LINE = re.compile(r"\n\s*\n")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")  # a Markdown heading: its marks, its text
LIST_ITEM = re.compile(r"^([-*+]|\d+\.)(\s+|$)")  # a Markdown list item's marker


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


def held_out(pages: Mapping[str, str], exclude: set[str], seed: int) -> list[str]:
    """W2b's pages: each type to its HELD_OUT quota, from pages outside `exclude`
    (W1's sample), for checking a fix on pages it was not derived from."""
    rng = random.Random(seed)
    chosen: list[str] = []
    for kind, quota in [*HELD_OUT.items(), ("other", HELD_OUT_OTHER)]:
        pool = sorted(s for s in pages if page_type(s) == kind and s not in exclude)
        chosen += rng.sample(pool, min(quota, len(pool)))
    return chosen


def router(served: dict[str, str]) -> Callable[[Any], None]:
    """A request handler: a page being rendered is served from the cache; what a
    visitor's browser loads for it (the site's assets, the script libraries and fonts
    it names) loads; trackers and embedded widgets are blocked."""

    def handle(route: Any) -> None:
        url = route.request.url
        if url in served:
            route.fulfill(body=served[url], content_type="text/html; charset=utf-8")
        elif any(host in urlsplit(url).netloc for host in BLOCKED):
            route.abort()
        else:
            route.continue_()

    return handle


def reveal(page: Any) -> None:
    """Show the page as a visitor who scrolls through it does: dismiss the cookie
    notice, then scroll to the end so scroll-triggered content appears."""
    for button in page.get_by_role("button", name=CONSENT).all():
        if button.is_visible():
            button.click()
    height = int(page.evaluate("document.body.scrollHeight"))
    for top in range(0, height + VIEWPORT["height"], VIEWPORT["height"] // 2):
        page.evaluate(f"window.scrollTo(0, {top})")
        page.wait_for_timeout(SETTLE_MS)
    open_answers(page)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(SETTLE_MS)


def open_answers(page: Any) -> None:
    """Open each hidden answer of a definition-list accordion (the FAQ) as a visitor
    does, by clicking its term. The site's accordion shows one answer at a time, so
    each answer that opened is marked, then all marked answers are shown together:
    the kept text and screenshot hold every answer a visitor can open, in place."""
    for term in page.locator("dl > dt").all():
        answer = term.locator("xpath=following-sibling::dd[1]")
        if not term.is_visible() or answer.is_visible():
            continue
        term.click()
        page.wait_for_timeout(OPEN_MS)
        if answer.is_visible():
            answer.evaluate("e => e.dataset.opened = 'yes'")
    page.wait_for_timeout(OPEN_MS)
    page.evaluate(
        "document.querySelectorAll('[data-opened]')"
        ".forEach(e => e.style.display = 'block')"
    )


def render(
    slugs: Sequence[str], cached: Mapping[str, str], out: Path, browser: Any
) -> dict[str, int]:
    """Each page's screenshot and visible text in `out`; its visible word count."""
    out.mkdir(parents=True, exist_ok=True)
    served: dict[str, str] = {}
    page = browser.new_page(viewport=VIEWPORT)
    page.route("**/*", router(served))
    counts = {}
    for slug in slugs:
        url = ingest.page_url(slug)
        served.clear()
        served[url] = cached[slug]
        page.goto(url, wait_until="networkidle")
        reveal(page)
        page.screenshot(path=str(out / f"{slug}.png"), full_page=True)
        text = str(page.evaluate("document.body.innerText"))
        (out / f"{slug}.txt").write_text(text, encoding="utf-8")
        counts[slug] = len(text.split())
        time.sleep(config.REQUEST_DELAY_SECONDS)
    page.close()
    return counts


@contextmanager
def chromium() -> Iterator[Any]:
    """Playwright's headless Chromium (the `bench` group)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def visible_lines(text: str) -> list[str]:
    """A rendered page's visible text as the outlines number it: non-empty lines."""
    return [line.strip() for line in text.split("\n") if line.strip()]


def outline_lines(outline: Mapping[str, Any]) -> list[int]:
    """The visible lines an outline's blocks use (the title apart), in its order."""
    used: list[int] = []
    for entry in outline["blocks"]:
        kind = entry[0]
        if kind == "h":
            used.append(entry[2])
        elif kind in ("p", "meta"):
            used += range(entry[1], entry[-1] + 1)
        elif kind == "list":
            step = entry[3] if len(entry) > 3 else 1
            used += range(entry[1], entry[2] + 1, step)
    return used


def outline_problems(outline: Mapping[str, Any], count: int) -> list[str]:
    """Lines an outline uses beyond the page's `count` lines, twice or out of
    reading order: slips made while judging."""
    used = outline_lines(outline)
    title = outline["title"]
    problems = [f"line {n} beyond the page" for n in [title, *used] if n >= count]
    problems += [f"line {b} after line {a}" for a, b in pairwise(used) if b <= a]
    if title in used:
        problems.append(f"title line {title} used again")
    return problems


def build_truth(outline: Mapping[str, Any], lines: Sequence[str]) -> dict[str, Any]:
    """A page's truth from its outline over `lines`: the title, the headings with their
    levels, and the main content's blocks in order, each with its section path (the
    headings above it, outermost first). Entries: ["h", level, line], ["meta", line],
    ["p", first, last] (one paragraph per line), ["list", first, last, step] (one
    block; the step, 1 if left out, skips link lines between items), ["alt", text]
    and ["end", level] (closes the sections at that level and below: a block after
    it stands outside them). The site has no HTML tables, so no table kind."""
    path: list[tuple[int, str]] = []
    headings = []
    blocks: list[dict[str, Any]] = []
    for entry in outline["blocks"]:
        kind = entry[0]
        if kind == "end":
            path = [(n, h) for n, h in path if n < entry[1]]
            continue
        if kind == "h":
            level, text = entry[1], lines[entry[2]]
            path = [(n, h) for n, h in path if n < level] + [(level, text)]
            headings.append({"level": level, "text": text})
            continue
        section = [heading for _, heading in path]
        if kind == "alt":
            blocks.append({"kind": kind, "text": entry[1], "path": section})
        elif kind in ("p", "meta"):
            for number in range(entry[1], entry[-1] + 1):
                blocks.append({"kind": kind, "text": lines[number], "path": section})
        else:
            step = entry[3] if len(entry) > 3 else 1
            rows = list(lines[entry[1] : entry[2] + 1 : step])
            blocks.append({"kind": kind, "items": rows, "path": section})
    return {"title": lines[outline["title"]], "headings": headings, "blocks": blocks}


def tokens(text: str) -> list[str]:
    """Words as W2 compares them: compatibility forms and case folded, runs of
    letters and digits (punctuation and typography do not count)."""
    return WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def squash(text: str) -> str:
    """A text's letters and digits only, for finding one text inside another."""
    return "".join(tokens(text))


def current_reading(raw: str) -> dict[str, Any]:
    """Arm (a): `ingest.extract_sections` as it stands, each section's path its one
    heading (the first is the title when no heading comes before the text)."""
    title, found = ingest.extract_sections(raw)
    headings = [heading for heading, _ in found]
    if headings and headings[0] == title:
        headings = headings[1:]
    sections = [{"path": [heading], "texts": texts} for heading, texts in found]
    return {"title": title, "headings": headings, "sections": sections}


def markdown_reading(markdown: str) -> dict[str, Any]:
    """Arms (b) and (c): a Markdown page's reading. A line of `#`s is a heading at
    that level (the first level-1 heading is the title); paragraphs and list items
    are texts under the headings above them; image marks are skipped."""
    title = ""
    headings: list[str] = []
    path: list[tuple[int, str]] = []
    sections: list[dict[str, Any]] = []

    def add(texts: list[str]) -> None:
        here = [heading for _, heading in path]
        kept = [text for text in texts if text]
        if not kept:
            return
        if not sections or sections[-1]["path"] != here:
            sections.append({"path": here, "texts": []})
        sections[-1]["texts"] += kept

    for block in BLANK_LINE.split(markdown):
        texts: list[str] = []
        for line in (line.strip() for line in block.split("\n")):
            heading = HEADING.match(line)
            item = LIST_ITEM.match(line)
            if heading:
                add(texts)
                texts = []
                level, text = len(heading[1]), ingest.clean(heading[2])
                if level == 1 and not title:
                    title = text
                    continue
                headings.append(text)
                path = [(n, h) for n, h in path if n < level] + [(level, text)]
            elif item:
                texts.append(line[item.end() :])
            elif line and not line.startswith("<!--"):
                if texts:
                    texts[-1] = f"{texts[-1]} {line}".strip()
                else:
                    texts.append(line)
        add(texts)
    return {"title": title, "headings": headings, "sections": sections}


def docling_converter() -> Any:
    """Docling's converter for HTML (the `ingest` group)."""
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter

    return DocumentConverter(allowed_formats=[InputFormat.HTML])


def docling_reading(raw: str, converter: Any) -> dict[str, Any]:
    """Arm (b): Docling's HTML backend on the main content after (a)'s furniture
    removal (alone it reads the site's menus), exported as Markdown."""
    from docling.datamodel.base_models import DocumentStream

    html = BytesIO(str(main_content(raw)).encode("utf-8"))
    result = converter.convert(DocumentStream(name="page.html", stream=html))
    return markdown_reading(result.document.export_to_markdown())


def trafilatura_reading(raw: str) -> dict[str, Any]:
    """Arm (c): trafilatura's own content detection on the whole page, as Markdown
    (the `bench` group)."""
    import trafilatura

    return markdown_reading(trafilatura.extract(raw, output_format="markdown") or "")


def holder(text: str, sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The section holding a truth block's text (letters and digits compared), else
    the one sharing most of its words, else None."""
    target = squash(text)
    for section in sections:
        if target in squash(" ".join(section["texts"])):
            return section
    wanted = Counter(tokens(text))
    shared = [
        sum((wanted & Counter(tokens(" ".join(section["texts"])))).values())
        for section in sections
    ]
    best = max(shared, default=0)
    return sections[shared.index(best)] if best else None


def in_order(parts: list[str], text: str) -> bool:
    """Whether every part occurs in `text`, each after the one before."""
    position = 0
    for part in parts:
        found = text.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def page_score(page: Mapping[str, Any], reading: Mapping[str, Any]) -> dict[str, int]:
    """One page's counts for W2's measures (X42 report)."""
    blocks = page["blocks"]
    shown = [page["title"], *(heading["text"] for heading in page["headings"])]
    for block in blocks:
        if block["kind"] == "list":
            shown += block["items"]
        elif block["kind"] != "alt":
            shown.append(block["text"])
    alts = [block["text"] for block in blocks if block["kind"] == "alt"]
    sections = reading["sections"]
    kept = [
        reading["title"],
        *reading["headings"],
        *(text for section in sections for text in section["texts"]),
    ]
    truth = Counter(tokens(" ".join(shown)))
    words = Counter(tokens(" ".join(kept)))
    allowed = truth + Counter(tokens(" ".join(alts)))
    named = Counter(squash(heading["text"]) for heading in page["headings"])
    found_headings = named & Counter(squash(heading) for heading in reading["headings"])
    tested = placed = 0
    for block in blocks:
        if block["kind"] not in ("p", "list") or not block["path"]:
            continue
        tested += 1
        held = holder(block.get("text") or " ".join(block["items"]), sections)
        above = {squash(heading) for heading in held["path"]} if held else set()
        placed += {squash(heading) for heading in block["path"]} <= above
    lists = [block["items"] for block in blocks if block["kind"] == "list"]
    whole = sum(
        any(
            in_order([squash(item) for item in items], squash(" ".join(s["texts"])))
            for s in sections
        )
        for items in lists
    )
    everything = squash(" ".join(kept))
    return {
        "words": sum(truth.values()),
        "found": sum((truth & words).values()),
        "kept": sum(words.values()),
        "right": sum((allowed & words).values()),
        "headings": sum(named.values()),
        "headings_found": sum(found_headings.values()),
        "tested": tested,
        "placed": placed,
        "lists": len(lists),
        "lists_whole": whole,
        "alts": len(alts),
        "alts_kept": sum(squash(alt) in everything for alt in alts),
    }


def scores(
    truth: Mapping[str, Any], readings: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Every page's counts, their totals, and W2's rates over the totals."""
    pages = {slug: page_score(page, readings[slug]) for slug, page in truth.items()}
    total: Counter[str] = Counter()
    for counts in pages.values():
        total.update(counts)
    rates = {
        "recall": total["found"] / total["words"],
        "precision": total["right"] / total["kept"],
        "headings": total["headings_found"] / total["headings"],
        "section_paths": total["placed"] / total["tested"],
        "lists": total["lists_whole"] / total["lists"],
        "alts": total["alts_kept"] / total["alts"],
    }
    return {"rates": rates, "total": dict(total), "pages": pages}

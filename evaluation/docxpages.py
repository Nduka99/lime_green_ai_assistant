"""X43 A3a: Word documents read against truth judged from their rendered pages.

A document is scored whole, since one arm (Docling's Word reader) has no pages: its
truth pages are pooled. Text, label-value pairs, ruled-grid values and numbers use
X8's measures (`evaluation.parsing`); images count the figures read; headings count
truth headings read as headings.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from evaluation import parsing
from limespec import layout
from limespec.elements import Element

BARS = {"words": 0.99, "numbers": 1.0, "grid": 0.95, "pairs": 0.95, "images": 1.0}


def document_counts(
    pages: Sequence[Mapping[str, Any]], found: Sequence[Element]
) -> dict[str, tuple[int, int]]:
    """One document's (found, total) counts for each measure."""
    lines = [line for page in pages for line in page["lines"]]
    pairs = [pair for page in pages for pair in page["pairs"]]
    tables = [table for page in pages for table in page["tables"]]
    images = sum(len(page["images"]) for page in pages)
    headings = [heading for page in pages for heading in page["headings"]]
    units = [e.text for e in found if e.text and e.kind != "table"]
    grids = [e.grid for e in found if e.kind == "table"]
    reference = "\n".join(lines)
    text = parsing.squash(" ".join(e.text for e in found))  # tables included
    numbers = [n for line in lines for n in parsing.NUMBER.findall(line)]
    read = parsing.words(" ".join(units))
    wanted = parsing.words(reference)
    read_headings = {parsing.squash(e.text) for e in found if e.kind == "heading"}
    grid_found, grid_total, _ = parsing.grid_cells(tables, grids)
    figures = sum(e.kind == "figure" for e in found)
    return {
        "words": parsing.words_kept(reference, units),
        "precision": (sum((wanted & read).values()), sum(read.values())),
        "numbers": (sum(n in text for n in numbers), len(numbers)),
        "pairs": parsing.pairs_kept(pairs, units),
        "grid": (grid_found, grid_total),
        "images": (min(figures, images), images),
        "headings": (
            sum(parsing.squash(h) in read_headings for h in headings),
            len(headings),
        ),
    }


def scores(
    truth: Sequence[Mapping[str, Any]], readings: Mapping[str, Sequence[Element]]
) -> dict[str, Any]:
    """Every document's counts (by SHA-256), the pooled rates and the bars."""
    documents: dict[str, list[Mapping[str, Any]]] = {}
    for page in truth:
        documents.setdefault(page["sha256"], []).append(page)
    rows = {
        sha: document_counts(pages, readings[sha]) for sha, pages in documents.items()
    }
    totals: dict[str, Counter[str]] = {}
    for counts in rows.values():
        for measure, (found, total) in counts.items():
            totals.setdefault(measure, Counter()).update(
                {"found": found, "total": total}
            )
    rates = {
        measure: count["found"] / count["total"] if count["total"] else 1.0
        for measure, count in totals.items()
    }
    passed = {measure: rates[measure] >= bar for measure, bar in BARS.items()}
    return {"rates": rates, "passed": passed, "documents": rows}


def element(record: Mapping[str, Any]) -> Element:
    """An element saved as JSON (`dataclasses.asdict`) read back."""
    box = record["bbox"]
    return Element(
        page=record["page"],
        kind=record["kind"],
        text=record["text"],
        section=tuple(record["section"]),
        bbox=(box[0], box[1], box[2], box[3]) if box else None,
        table=record["table"],
        row=record["row"],
        cells=tuple((header, value) for header, value in record["cells"]),
        grid=tuple(tuple(row) for row in record["grid"]),
    )


def page_measures(
    page: Mapping[str, Any], found: Sequence[Element], reference: str
) -> dict[str, Any]:
    """X8's measures for one truth page, as `evaluation parsing` takes them."""
    units = [e.text for e in found if e.text and e.kind != "table"]
    rows = [e.cells for e in found if e.kind == "table_row"]
    grids = [e.grid for e in found if e.kind == "table"]
    return parsing.score_page(dict(page), units, rows, reference, grids)


def layout_check(
    truth: Sequence[Mapping[str, Any]], saved: Mapping[str, Any], arm: str
) -> dict[str, Any]:
    """Each X8 page's measures from a saved reading, as read and with side-by-side
    blocks joined (`layout.side_by_side`); the pages and measures that fall."""
    falls = []
    pooled: dict[str, list[dict[str, Any]]] = {"before": [], "after": []}
    for page in truth:
        record = saved[str(page["number"])]
        found = [element(item) for item in record[arm]]
        reference = "\n".join(record["pypdf"])
        before = page_measures(page, found, reference)
        after = page_measures(page, layout.side_by_side(found), reference)
        pooled["before"].append(before)
        pooled["after"].append(after)
        for measure in [*parsing.GATE, "grid"]:
            if after[measure][0] < before[measure][0]:
                falls.append(f"page {page['number']} {measure}")
    return {
        "before": parsing.pooled(pooled["before"]),
        "after": parsing.pooled(pooled["after"]),
        "falls": falls,
    }

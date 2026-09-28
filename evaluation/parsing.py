"""Score PDF parsers against ground truth written from page images (experiment X8).

Each parser's output for a page is a list of text units in reading order (the text
layer's lines, or Docling's elements) plus any table rows it rebuilt. The measures
and the gate are the ones registered in evaluation/reports/X8-pdf-parsing.md.
Everything is compared with whitespace removed and case ignored, so spacing
differences (a superscript read as "m 2") never count as errors.
"""

import re
import statistics
from collections import Counter
from typing import Any

Rows = list[tuple[tuple[str, str], ...]]  # table rows as (header, value) cells
NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)?")
# Punctuation at a word's edges: a rebuilt table row adds separators ("A1;").
EDGES = ".,;:!?()[]{}\"'‘’“”—–-"
GATE = {"cells": 0.95, "pairs": 0.95, "words": 0.99, "sentences": 0.95, "numbers": 0.99}
LOWEST_TABLE = 0.80


def squash(text: str) -> str:
    return "".join(text.split()).casefold()


def cell_found(label: str, header: str, value: str, rows: Rows) -> bool:
    """Whether a parsed row with this label holds this value under this header. A
    parsed header joins the header rows above it ("Performance Class i"), so it must
    end with the truth header; "Class i" must not match "Class ii"."""
    for cells in rows:
        if not cells or squash(label) not in squash(cells[0][1]):
            continue
        for column_header, cell in cells[1:]:
            same_column = squash(column_header).endswith(squash(header))
            if same_column and squash(cell) == squash(value):
                return True
    return False


def table_cells(
    tables: list[dict[str, Any]], rows: Rows
) -> tuple[int, int, list[float]]:
    """Truth cells found as (row label, column header, value); each table's share."""
    found = 0
    total = 0
    shares = []
    for table in tables:
        header = table["header"]
        hits = 0
        cells = 0
        for row in table["rows"]:
            for column in range(1, len(row)):
                if not row[column]:
                    continue
                cells += 1
                if cell_found(row[0], header[column], row[column], rows):
                    hits += 1
        found += hits
        total += cells
        shares.append(hits / cells if cells else 1.0)
    return found, total, shares


def words(text: str) -> Counter[str]:
    """The text's words, without case or punctuation at their edges."""
    found = (word.strip(EDGES) for word in text.casefold().split())
    return Counter(word for word in found if word)


def words_kept(reference: str, units: list[str]) -> tuple[int, int]:
    """Text-layer words that appear in the parser's text, counted as a multiset."""
    wanted = words(reference)
    have = words(" ".join(units))
    kept = sum(min(count, have[word]) for word, count in wanted.items())
    return kept, sum(wanted.values())


def sentences_whole(sentences: list[str], units: list[str]) -> tuple[int, int]:
    """Truth sentences found as continuous text in the parser's reading order."""
    text = squash(" ".join(units))
    return sum(squash(sentence) in text for sentence in sentences), len(sentences)


def table_numbers(tables: list[dict[str, Any]], units: list[str]) -> tuple[int, int]:
    """Numbers in truth table cells that appear in the parser's text."""
    text = squash(" ".join(units))
    numbers = [
        number
        for table in tables
        for row in table["rows"]
        for value in row
        for number in NUMBER.findall(value)
    ]
    return sum(number in text for number in numbers), len(numbers)


def pairs_kept(pairs: list[list[str]], units: list[str]) -> tuple[int, int]:
    """Label-value pairs whose value sits in the label's unit or the next one."""
    kept = 0
    squashed = [squash(unit) for unit in units]
    for label, value in pairs:
        for index, unit in enumerate(squashed):
            if squash(label) not in unit:
                continue
            following = squashed[index + 1] if index + 1 < len(squashed) else ""
            if squash(value) in unit or squash(value) in following:
                kept += 1
                break
    return kept, len(pairs)


def score_page(
    page: dict[str, Any], units: list[str], rows: Rows, reference: str
) -> dict[str, Any]:
    """Every measure for one parser on one truth page, as (found, total) counts."""
    found, total, shares = table_cells(page["tables"], rows)
    return {
        "cells": (found, total),
        "table_shares": shares,
        "pairs": pairs_kept(page["pairs"], units),
        "words": words_kept(reference, units),
        "sentences": sentences_whole(page["sentences"], units),
        "numbers": table_numbers(page["tables"], units),
    }


def pooled(pages: list[dict[str, Any]]) -> dict[str, float]:
    """Each measure's share over all pages (1.0 where a measure has nothing to find)."""
    result = {}
    for measure in GATE:
        found = sum(page[measure][0] for page in pages)
        total = sum(page[measure][1] for page in pages)
        result[measure] = found / total if total else 1.0
    return result


def gate(
    docling: dict[str, float], pypdf: dict[str, float], lowest: float
) -> dict[str, bool]:
    """The registered gate, item by item."""
    return {
        "1. table cells and pairs": docling["cells"] >= GATE["cells"]
        and docling["pairs"] >= GATE["pairs"]
        and lowest >= LOWEST_TABLE,
        "2. text kept": docling["words"] >= GATE["words"],
        "3. sentences whole": docling["sentences"] >= GATE["sentences"]
        and docling["sentences"] >= pypdf["sentences"],
        "4. table numbers": docling["numbers"] >= GATE["numbers"],
    }


def markdown(result: dict[str, Any]) -> str:
    """The scores of both parsers, the lowest table and the gate, as a report table."""
    lines = [
        "| Measure | pypdf | docling | Gate |",
        "|---|---|---|---|",
    ]
    for measure, threshold in GATE.items():
        pypdf = result["pypdf"][measure]
        docling = result["docling"][measure]
        lines.append(f"| {measure} | {pypdf:.3f} | {docling:.3f} | >= {threshold} |")
    lines.append("")
    lines.append(
        f"Lowest table (docling): {result['lowest_table']:.3f} (>= {LOWEST_TABLE})"
    )
    lines.append(
        f"Docling seconds per page: median {result['seconds']['median']:.1f}, "
        f"first {result['seconds']['first']:.1f} (loads the models)"
    )
    for item, passed in result["gate"].items():
        lines.append(f"- {item}: {'pass' if passed else 'FAIL'}")
    return "\n".join(lines)


def summarise(
    scores: dict[str, list[dict[str, Any]]], seconds: list[float]
) -> dict[str, Any]:
    """Pooled measures per parser, the lowest docling table and the gate."""
    docling = pooled(scores["docling"])
    pypdf = pooled(scores["pypdf"])
    shares = [share for page in scores["docling"] for share in page["table_shares"]]
    lowest = min(shares, default=1.0)
    return {
        "pypdf": pypdf,
        "docling": docling,
        "lowest_table": lowest,
        "seconds": {"median": statistics.median(seconds), "first": seconds[0]},
        "gate": gate(docling, pypdf, lowest),
    }

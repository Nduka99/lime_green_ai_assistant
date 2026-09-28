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
# Round 2's bar for indexing a model's transcriptions as searchable text.
TRANSCRIPTION = {"recall": 0.90, "precision": 0.95}


# Docling's PDF parser writes typographic characters in their plain form (its
# default sanitisation), so both sides of every comparison are folded the same way.
TYPOGRAPHY = str.maketrans(dict.fromkeys('‘’“”"', "'") | dict.fromkeys("–—", "-"))


def fold(text: str) -> str:
    return text.translate(TYPOGRAPHY).casefold()


def squash(text: str) -> str:
    return "".join(fold(text).split())


def cell_found(label: str, header: str, value: str, rows: Rows) -> bool:
    """Whether a parsed row with this label holds this value under this header. A
    parsed header keeps its levels ("Performance › Class i"); the truth header must be
    one of them ("Class i" must not match "Class ii"), or empty for any column."""
    for cells in rows:
        if not cells or squash(label) not in squash(cells[0][1]):
            continue
        for column_header, cell in cells[1:]:
            parts = {squash(part) for part in column_header.split(" › ")}
            same_column = not header or squash(header) in parts
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
    found = (word.strip(EDGES) for word in fold(text).split())
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
    arm: dict[str, float], pypdf: dict[str, float], lowest: float
) -> dict[str, bool]:
    """The registered gate, item by item, for one arm."""
    return {
        "1. table cells and pairs": arm["cells"] >= GATE["cells"]
        and arm["pairs"] >= GATE["pairs"]
        and lowest >= LOWEST_TABLE,
        "2. text kept": arm["words"] >= GATE["words"],
        "3. sentences whole": arm["sentences"] >= GATE["sentences"]
        and arm["sentences"] >= pypdf["sentences"],
        "4. table numbers": arm["numbers"] >= GATE["numbers"],
    }


def markdown(result: dict[str, Any]) -> str:
    """The scores of the text layer and the arm, the lowest table and the gate, as a
    report table."""
    arm = result["arm"]
    lines = [
        f"| Measure | pypdf | {arm} | Gate |",
        "|---|---|---|---|",
    ]
    for measure, threshold in GATE.items():
        pypdf = result["pypdf"][measure]
        score = result[arm][measure]
        lines.append(f"| {measure} | {pypdf:.3f} | {score:.3f} | >= {threshold} |")
    lines.append("")
    shares = ", ".join(f"{share:.3f}" for share in result["table_shares"])
    lines.append(
        f"Lowest table ({arm}): {result['lowest_table']:.3f} (>= {LOWEST_TABLE}); "
        f"each table: {shares}"
    )
    seconds = result["seconds"]
    lines.append(
        f"Seconds per page ({arm}): mean {seconds['mean']:.1f}, median "
        f"{seconds['median']:.1f}, first {seconds['first']:.1f} (loads the models)"
    )
    for item, passed in result["gate"].items():
        lines.append(f"- {item}: {'pass' if passed else 'FAIL'}")
    return "\n".join(lines)


def summarise(
    scores: dict[str, list[dict[str, Any]]], seconds: list[float], arm: str = "docling"
) -> dict[str, Any]:
    """Pooled measures for the text layer and the arm, the arm's lowest table and its
    gate."""
    measured = pooled(scores[arm])
    pypdf = pooled(scores["pypdf"])
    shares = [share for page in scores[arm] for share in page["table_shares"]]
    lowest = min(shares, default=1.0)
    return {
        "arm": arm,
        "pypdf": pypdf,
        arm: measured,
        "lowest_table": lowest,
        "table_shares": shares,
        "seconds": {
            "mean": statistics.mean(seconds),
            "median": statistics.median(seconds),
            "first": seconds[0],
        },
        "gate": gate(measured, pypdf, lowest),
    }


def transcription(truth: str, answer: str) -> dict[str, tuple[int, int]]:
    """Recall (truth words the transcription holds) and precision (transcribed
    words the truth holds), counted as multisets of words with a letter or digit,
    markup removed."""
    wanted = _alphanumeric(words(truth))
    have = _alphanumeric(words(re.sub(r"<[^>]+>", " ", answer)))
    common = sum((wanted & have).values())
    return {
        "recall": (common, sum(wanted.values())),
        "precision": (common, sum(have.values())),
    }


def _alphanumeric(counts: Counter[str]) -> Counter[str]:
    return Counter({w: n for w, n in counts.items() if any(c.isalnum() for c in w)})

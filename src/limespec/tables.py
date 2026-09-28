"""Tables read again from their image by a small vision-language model (X8, round 2).

Docling finds each table and its box. A model such as GLM-OCR or PaddleOCR-VL reads
the table's image and answers with its structure: rows, columns, spans and, in HTML,
header cells. The model's own text is never kept. Each cell must be spelt by words of
the PDF inside the table's box, each word used once, and those words become the
cell's text, so every quote stays the document's own characters. A cell they cannot
spell is left empty and counted.
"""

from __future__ import annotations

import base64
import io
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import httpx

from limespec import llm

if TYPE_CHECKING:
    from PIL.Image import Image

PROMPT = "Table Recognition:"  # both models' prompt for a table
MAX_TOKENS = 8192  # GLM-OCR's published limit
TIMEOUT_SECONDS = 600.0  # a large table can take minutes
OTSL = re.compile(r"(<fcel>|<ecel>|<lcel>|<ucel>|<xcel>|<nl>)")
TYPOGRAPHY = str.maketrans(dict.fromkeys('‘’“”"', "'") | dict.fromkeys("–—", "-"))


@dataclass(frozen=True)
class Cell:
    """One cell of the model's table: where it starts, how far it spans, its text."""

    row: int
    column: int
    text: str
    rows: int = 1
    columns: int = 1
    header: bool = False


def recognise(image: Image, url: str, prompt: str = PROMPT) -> str:
    """The model's reading of an image, from the llama.cpp server at `url`. Sampling
    settings are the server's own, set when it starts with the model's published
    values."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        {"type": "text", "text": prompt},
    ]
    body = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": MAX_TOKENS,
    }
    try:
        response = httpx.post(
            f"{url}/v1/chat/completions",
            json=body,
            headers=llm.auth(),
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise llm.ModelServerError(f"vision model at {url} failed: {error}") from error


def parse(answer: str) -> list[Cell]:
    """The cells of a table answer written as HTML (GLM-OCR) or OTSL (PaddleOCR-VL);
    none when the answer is neither."""
    if "<table" in answer.casefold():
        return parse_html(answer)
    if OTSL.search(answer):
        return parse_otsl(answer)
    return []


class _Table(HTMLParser):
    """Collects each row's cells as (text, rows spanned, columns spanned, header)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, int, int, bool]]] = []
        self.text: list[str] | None = None  # the open cell's text
        self.span = (1, 1)
        self.header = False
        self.head = False  # inside <thead>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "thead":
            self.head = True
        elif tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            values = dict(attrs)
            self.span = (_span(values.get("rowspan")), _span(values.get("colspan")))
            self.header = tag == "th" or self.head
            self.text = []
        elif tag == "br" and self.text is not None:
            self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "thead":
            self.head = False
        elif tag in ("td", "th") and self.text is not None:
            text = " ".join("".join(self.text).split())
            self.rows[-1].append((text, *self.span, self.header))
            self.text = None

    def handle_data(self, data: str) -> None:
        if self.text is not None:
            self.text.append(data)


def _span(value: str | None) -> int:
    return int(value) if value and value.isdigit() and int(value) > 0 else 1


def parse_html(answer: str) -> list[Cell]:
    """An HTML table's cells at their grid positions: a position already covered by a
    cell spanning down from above is skipped, as browsers lay tables out."""
    table = _Table()
    table.feed(answer)
    taken: set[tuple[int, int]] = set()
    cells = []
    for row, found in enumerate(table.rows):
        column = 0
        for text, down, across, header in found:
            while (row, column) in taken:
                column += 1
            cells.append(Cell(row, column, text, down, across, header))
            taken |= {(row + i, column + j) for i in range(down) for j in range(across)}
            column += across
    return cells


def parse_otsl(answer: str) -> list[Cell]:
    """An OTSL table's cells: `<nl>` ends a row, `<fcel>` starts a cell with text and
    `<ecel>` an empty one; `<lcel>`, `<ucel>` and `<xcel>` extend the cell on the left,
    above, or both ([OTSL](https://arxiv.org/abs/2305.03393))."""
    grid: list[list[tuple[str, str]]] = [[]]
    parts = OTSL.split(answer)
    for index in range(1, len(parts), 2):
        tag, text = parts[index], parts[index + 1]
        if tag == "<nl>":
            grid.append([])
        else:
            grid[-1].append((tag, " ".join(text.split())))
    grid = [row for row in grid if row]
    cells = []
    for row, tags in enumerate(grid):
        for column, (tag, text) in enumerate(tags):
            if tag not in ("<fcel>", "<ecel>"):
                continue
            across = 1
            while column + across < len(tags) and tags[column + across][0] in (
                "<lcel>",
                "<xcel>",
            ):
                across += 1
            down = 1
            while (
                row + down < len(grid)
                and column < len(grid[row + down])
                and grid[row + down][column][0] in ("<ucel>", "<xcel>")
            ):
                down += 1
            cells.append(Cell(row, column, text, down, across))
    return cells


def fold(text: str) -> str:
    """Text for comparison only: no whitespace, case, typographic or compatibility
    variants (a superscript ² is a 2)."""
    plain = unicodedata.normalize("NFKC", text).translate(TYPOGRAPHY)
    return "".join(plain.casefold().split())


def spell(text: str, words: list[str], used: set[int]) -> list[int] | None:
    """The unused words, by index, that spell `text` once folded and joined, taken in
    reading order where possible; None when the words cannot spell it."""
    return _spell(fold(text), [fold(word) for word in words], frozenset(used), 0)


def _spell(
    rest: str, words: list[str], used: frozenset[int], start: int
) -> list[int] | None:
    if not rest:
        return []
    tried = set()
    for index in [*range(start, len(words)), *range(start)]:
        word = words[index]
        if index in used or not word or word in tried or not rest.startswith(word):
            continue
        tried.add(word)  # the same word elsewhere spells the same rest
        tail = _spell(rest[len(word) :], words, used | {index}, index + 1)
        if tail is not None:
            return [index, *tail]
    return None


def structure(
    cells: list[Cell], words: list[str], header_rows: set[str]
) -> tuple[list[str], list[tuple[int, list[str]]], int]:
    """The table's column headers and its data rows, each cell's text spelt by the
    PDF's `words` (a cell they cannot spell is left empty), and how many cells were
    left empty. Header rows are those the model marks; if it marks none, those whose
    folded text is one of `header_rows` (the rows Docling flagged). A header spanning
    columns heads each of them; a value spanning rows is repeated in each row, and a
    value spanning columns is written once."""
    used: set[int] = set()
    texts = {}
    dropped = 0
    for cell in cells:
        found = spell(cell.text, words, used)
        if found is None:
            dropped += 1
        used.update(found or [])
        texts[cell] = " ".join(words[index] for index in found or [])
    height = max(cell.row + cell.rows for cell in cells)
    width = max(cell.column + cell.columns for cell in cells)
    starting = {
        row: [cell for cell in cells if cell.row == row] for row in range(height)
    }
    if any(cell.header for cell in cells):
        heads = {
            row
            for row, found in starting.items()
            if found and all(c.header for c in found)
        }
    else:
        heads = {
            row
            for row, found in starting.items()
            if found and fold(" ".join(texts[cell] for cell in found)) in header_rows
        }
    headers = []
    for column in range(width):
        parts: list[str] = []
        for cell in cells:
            if cell.row in heads and _covers(cell, cell.row, column):
                if texts[cell] and texts[cell] not in parts:
                    parts.append(texts[cell])
        headers.append(" › ".join(parts))
    rows = []
    for row in range(height):
        if row in heads:
            continue
        values = [""] * width
        for cell in cells:
            if _covers(cell, row, cell.column):
                values[cell.column] = texts[cell]
        if any(values):
            rows.append((row, values))
    return headers, rows, dropped


def _covers(cell: Cell, row: int, column: int) -> bool:
    return (
        cell.row <= row < cell.row + cell.rows
        and cell.column <= column < cell.column + cell.columns
    )

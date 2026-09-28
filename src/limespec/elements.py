"""The element model every parser returns (PLAN §0f): one piece of a document, in
reading order, with where it sits and what kind of text it is.

Everything after parsing (validation, passages, citations) reads only elements, so
a new parser only has to produce them. Plain, JSON-compatible data.
"""

from dataclasses import dataclass

# What an element is: a heading, running text, a list item, one table row, a
# caption, a figure (its caption), or page furniture (running headers and footers).
KINDS = ("heading", "paragraph", "list", "table_row", "caption", "figure", "furniture")


@dataclass(frozen=True)
class Element:
    page: int  # 1-based page number
    kind: str  # one of KINDS
    text: str
    section: tuple[str, ...] = ()  # the headings above it, outermost first
    # Left, top, right, bottom in points from the page's top-left corner.
    bbox: tuple[float, float, float, float] | None = None
    table: int | None = None  # the table's number in the document, for table rows
    row: int | None = None  # the row's number in its table
    # A table row's cells as (column header, value), the row's label first.
    cells: tuple[tuple[str, str], ...] = ()


def row_text(cells: tuple[tuple[str, str], ...], caption: str = "") -> str:
    """A table row as one quotable line: `caption › label — header: value; ...`, so
    each value keeps its row and column in the text that is searched and quoted."""
    label = cells[0][1] if cells else ""
    values = [
        f"{header}: {value}" if header else value
        for header, value in cells[1:]
        if value  # an empty cell adds nothing, not a bare "header:"
    ]
    text = label + (" — " if label and values else "") + "; ".join(values)
    return f"{caption} › {text}" if caption else text

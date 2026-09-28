"""Born-digital PDFs read with Docling into elements (PLAN §0f, experiment X8).

Docling's standard pipeline takes each page's own characters from the PDF, finds
the layout (headings, text, lists, tables, pictures) and rebuilds each table's
rows and columns from those characters, so quoted text stays the document's own.
OCR is off: pages without a text layer are handled separately, as transcription.
Any line of the PDF's text layer that Docling's reading lost (measured in X8: a
styled table heading) is added back after its page's elements, so no text is lost.

Docling and its models are imported only when a PDF is read, so the API never
needs the `ingest` dependency group.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from limespec.elements import Element, row_text

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc.document import DoclingDocument

# Docling's labels for each kind of element; any other text label is running text.
HEADINGS = {"title", "section_header"}
KINDS = {
    "list_item": "list",
    "caption": "caption",
    "page_header": "furniture",
    "page_footer": "furniture",
}
FIGURES = {"picture", "chart"}
# Running headers and footers are kept, so no text is lost; hidden or background
# text is left out.
CONTENT_LAYERS = ("body", "furniture", "notes")
# Docling's PDF parser writes typographic characters plainly (its default
# sanitisation), so the text layer is folded the same way before it is compared.
TYPOGRAPHY = str.maketrans(dict.fromkeys('‘’“”"', "'") | dict.fromkeys("–—", "-"))
EDGES = ".,;:!?()[]{}'-"


@cache
def converter() -> DocumentConverter:
    """Docling's converter, loading its layout and table models once."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def read_pdf(path: Path, first: int = 1, last: int = sys.maxsize) -> list[Element]:
    """The elements of pages `first` to `last` of a PDF in reading order, each page
    followed by any text-layer line its reading lost."""
    result = converter().convert(path, page_range=(first, last))
    found = elements(result.document)
    pages = PdfReader(path).pages
    ordered = []
    for page in range(first, min(last, len(pages)) + 1):
        on_page = [element for element in found if element.page == page]
        text = " ".join(element.text for element in on_page)
        lines = lost_lines(pages[page - 1].extract_text() or "", text)
        ordered += on_page + [Element(page, "recovered", line) for line in lines]
    return ordered


def squash(text: str) -> str:
    """Text without whitespace, case or typographic variants, for comparison only."""
    return "".join(text.translate(TYPOGRAPHY).casefold().split())


def lost_lines(text_layer: str, parsed: str) -> list[str]:
    """Text-layer lines holding a word found nowhere in the parsed text. Words are
    compared without spacing, so a line the parser only spaced differently ("m 2"
    for "m2") or split into table cells is not added twice."""
    have = squash(parsed)
    lost = []
    for line in text_layer.splitlines():
        words = [squash(word).strip(EDGES) for word in line.split()]
        if any(word and word not in have for word in words):
            lost.append(line.strip())
    return lost


def box(item: Any, document: DoclingDocument) -> tuple[float, float, float, float]:
    """The item's box on its first page, measured from the page's top-left corner."""
    prov = item.prov[0]
    height = document.pages[prov.page_no].size.height
    bbox = prov.bbox.to_top_left_origin(height)
    return (bbox.l, bbox.t, bbox.r, bbox.b)


def table_rows(
    item: Any, number: int, section: tuple[str, ...], document: DoclingDocument
) -> list[Element]:
    """The table's header row as one element, then one element per data row with
    each cell paired with its column's header. A header of several levels keeps its
    parts, top first, joined by " › " ("Performance › Class i")."""
    grid = item.data.grid
    if not grid:
        return []
    headers = []
    for column in range(len(grid[0])):
        texts: list[str] = []
        for row in grid:
            cell = row[column]
            if cell.column_header and cell.text and cell.text not in texts:
                texts.append(cell.text)
        headers.append(" › ".join(texts))
    caption = item.caption_text(document)
    rows = []
    if any(headers):
        # Kept as its own element, so header text is never lost, even over a column
        # of empty cells (a checklist's tick boxes).
        rows.append(
            Element(
                page=item.prov[0].page_no,
                kind="table_header",
                text=" | ".join(header for header in headers if header),
                section=section,
                bbox=box(item, document),
                table=number,
            )
        )
    for index, row in enumerate(grid):
        # A header row can hold empty, unflagged cells (a blank corner above the
        # row labels), but a data row never holds a column header.
        if any(cell.column_header for cell in row):
            continue
        cells = tuple(zip(headers, (cell.text for cell in row), strict=True))
        rows.append(
            Element(
                page=item.prov[0].page_no,
                kind="table_row",
                text=row_text(cells, caption),
                section=section,
                bbox=box(item, document),
                table=number,
                row=index,
                cells=cells,
            )
        )
    return rows


def elements(document: DoclingDocument) -> list[Element]:
    """A Docling document's elements in reading order, text inside pictures (such as
    a drawing's callouts) included, each with the headings above it."""
    from docling_core.types.doc.common.content_layer import ContentLayer

    layers = {ContentLayer(name) for name in CONTENT_LAYERS}
    found: list[Element] = []
    section: list[tuple[int, str]] = []  # (level, heading)
    tables = 0
    # Items differ by kind (text, table, picture), so they are read field by field.
    items: Iterable[tuple[Any, int]] = document.iterate_items(
        traverse_pictures=True, included_content_layers=layers
    )
    for item, _ in items:
        label = item.label.value
        if not getattr(item, "prov", None):
            continue
        path = tuple(heading for _, heading in section)
        # Read each item by what it carries: rows (a table, or a contents page read
        # as one), a caption (a figure), text, or text cells (key-value and form
        # regions).
        if hasattr(item, "data"):
            tables += 1
            found += table_rows(item, tables, path, document)
            continue
        if label in FIGURES:
            text = item.caption_text(document)
        elif hasattr(item, "text"):
            # `orig` is the text as it stands on the page, a list's numbering ("5.",
            # "ii.") included; `text` drops the numbering.
            text = item.orig or item.text
        else:
            text = " ".join(cell.text for cell in item.graph.cells)
        if label in HEADINGS:
            level = 0 if label == "title" else item.level
            section = [(lvl, h) for lvl, h in section if lvl < level] + [(level, text)]
        kind = "heading" if label in HEADINGS else KINDS.get(label, "paragraph")
        if label in FIGURES:
            kind = "figure"
        found.append(
            Element(
                page=item.prov[0].page_no,
                kind=kind,
                text=text,
                section=path,
                bbox=box(item, document),
            )
        )
    return found

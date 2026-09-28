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
from collections import Counter
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError

from limespec.elements import Element, grid_text, row_text

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc.document import DoclingDocument
    from PIL.Image import Image

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
# Pages are rendered at 200 DPI for a vision model, GLM-OCR's setting for PDFs.
IMAGES_SCALE = 200 / 72
# Reads a table again: (table item, its number, its section) → rows, or None.
Reread = Callable[[Any, int, tuple[str, ...]], "list[Element] | None"]


@cache
def converter(images_scale: float = 0.0) -> DocumentConverter:
    """Docling's converter, loading its layout and table models once. Given an
    `images_scale` (1 = 72 DPI), it also keeps each page rendered at that scale and
    the words it parsed, so a table can be read again from its image."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from limespec.rendering import OPTIONS, PdfiumRenderedBackend

    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    )
    if images_scale:
        options.generate_page_images = True
        options.generate_parsed_pages = True
        options.images_scale = images_scale
    # Pages are drawn by pdfium, not docling-parse's renderer (see limespec.rendering).
    pdf_format = PdfFormatOption(
        pipeline_options=options,
        backend=PdfiumRenderedBackend,
        backend_options=OPTIONS,
    )
    return DocumentConverter(format_options={InputFormat.PDF: pdf_format})


def read_pdf(
    path: Path,
    first: int = 1,
    last: int = sys.maxsize,
    vlm: str = "",
    stats: Counter[str] | None = None,
    grades: dict[int, str] | None = None,
) -> list[Element]:
    """The elements of pages `first` to `last` of a PDF in reading order, each page
    followed by any text-layer line its reading lost. Given the URL of a vision
    model's server (`vlm`), each table is read again from its image, and `stats`
    counts the tables and cells it read. `grades` receives each page's lowest
    Docling confidence grade (poor, fair, good, excellent)."""
    result = converter(IMAGES_SCALE if vlm else 0.0).convert(
        path, page_range=(first, last)
    )
    if grades is not None:
        for number, scores in result.confidence.pages.items():
            grades[number] = scores.low_grade.value
    reread = None
    if vlm:
        words = {
            page.page_no: page.parsed_page.word_cells
            for page in result.pages
            if page.parsed_page
        }
        counts = Counter[str]() if stats is None else stats

        def reread(item: Any, number: int, section: tuple[str, ...]) -> Any:
            return vlm_table(item, number, section, result.document, words, vlm, counts)

    found = elements(result.document, reread)
    layers = text_layers(path, first, last)
    ordered = []
    pages = {element.page for element in found} | set(layers)
    for page in sorted(page for page in pages if first <= page <= last):
        on_page = [element for element in found if element.page == page]
        text = " ".join(element.text for element in on_page)
        lines = lost_lines(layers.get(page, ""), text)
        ordered += on_page + [Element(page, "recovered", line) for line in lines]
    return ordered


def text_layers(path: Path, first: int = 1, last: int = sys.maxsize) -> dict[int, str]:
    """Pages `first` to `last` of the PDF's text layer, by page number; none when
    pypdf cannot read the file (AES encryption needs its cryptography extra), so
    Docling's reading then stands without a check."""
    try:
        pages = PdfReader(path).pages
        return {
            number: pages[number - 1].extract_text() or ""
            for number in range(first, min(last, len(pages)) + 1)
        }
    except (PyPdfError, DependencyError, ValueError):
        return {}


def coverage(text_layer: str, parsed: str) -> tuple[int, int]:
    """How many of the text layer's words the parsed text holds, of how many,
    compared without spacing, case or typographic variants (as `lost_lines`)."""
    have = squash(parsed)
    words = [squash(word).strip(EDGES) for word in text_layer.split()]
    words = [word for word in words if word]
    return sum(word in have for word in words), len(words)


def page_image(path: Path, page: int, scale: float) -> Image:
    """One page as Docling renders it, at `scale` (2 = 144 DPI)."""
    result = converter(scale).convert(path, page_range=(page, page))
    image = result.document.pages[page].image
    if image is None or image.pil_image is None:
        raise ValueError(f"page {page} of {path} was not rendered")
    return image.pil_image


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
    """The table as Docling reads it. A header of several levels keeps its parts, top
    first, joined by " › " ("Performance › Class i")."""
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
    # A header row can hold empty, unflagged cells (a blank corner above the row
    # labels), but a data row never holds a column header.
    rows = [
        (index, [cell.text for cell in row])
        for index, row in enumerate(grid)
        if not any(cell.column_header for cell in row)
    ]
    # Docling's grid repeats a spanning cell in each position it covers.
    whole = [[cell.text for cell in row] for row in grid]
    return table_elements(whole, headers, rows, item, number, section, document)


def table_elements(
    grid: list[list[str]],
    headers: list[str],
    rows: list[tuple[int, list[str]]],
    item: Any,
    number: int,
    section: tuple[str, ...],
    document: DoclingDocument,
) -> list[Element]:
    """The whole table as one element, then its header row, then one element per
    data row with each cell paired with its column's header."""
    caption = item.caption_text(document)
    whole = tuple(tuple(row) for row in grid)
    found = [
        Element(
            page=item.prov[0].page_no,
            kind="table",
            text=grid_text(whole, caption),
            section=section,
            bbox=box(item, document),
            table=number,
            grid=whole,
        )
    ]
    if any(headers):
        # Kept as its own element, so header text is never lost, even over a column
        # of empty cells (a checklist's tick boxes).
        found.append(
            Element(
                page=item.prov[0].page_no,
                kind="table_header",
                text=" | ".join(header for header in headers if header),
                section=section,
                bbox=box(item, document),
                table=number,
            )
        )
    for index, values in rows:
        cells = tuple(zip(headers, values, strict=True))
        found.append(
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
    return found


def header_words(item: Any) -> set[str]:
    """The folded words of the rows Docling flags as column headers."""
    from limespec.tables import fold

    found = set()
    for row in item.data.grid:
        if any(cell.column_header for cell in row):
            found |= {fold(word) for cell in row for word in cell.text.split()}
    return found


def words_inside(
    bbox: tuple[float, float, float, float], cells: list[Any], height: float
) -> list[str]:
    """The page's words, in the PDF's order, whose centre lies in the box (measured
    from the page's top-left corner)."""
    left, top, right, bottom = bbox
    words = []
    for cell in cells:
        rect = cell.rect.to_bounding_box().to_top_left_origin(height)
        x = (rect.l + rect.r) / 2
        y = (rect.t + rect.b) / 2
        if left <= x <= right and top <= y <= bottom:
            words.append(cell.text)
    return words


def vlm_table(
    item: Any,
    number: int,
    section: tuple[str, ...],
    document: DoclingDocument,
    words: dict[int, list[Any]],
    url: str,
    stats: Counter[str],
) -> list[Element] | None:
    """The table as a vision-language model reads its image, each cell spelt by the
    PDF's own words inside the table's box; None, so Docling's reading stands, when
    the answer is not a table."""
    from limespec import tables

    image = item.get_image(document)
    if image is None:
        return None
    stats["tables"] += 1
    cells = tables.parse(tables.recognise(image, url))
    if not cells:
        stats["unread"] += 1
        return None
    page = item.prov[0].page_no
    height = document.pages[page].size.height
    inside = words_inside(box(item, document), words.get(page, []), height)
    read = tables.structure(cells, inside, header_words(item))
    stats["cells"] += len(cells)
    stats["dropped"] += read.dropped
    found = table_elements(
        read.grid, read.headers, read.rows, item, number, section, document
    )
    if read.leftover:
        # The PDF's words no cell used (tick boxes, a value the model left out) are
        # kept, so reading a table again never loses text.
        text = " ".join(read.leftover)
        found.append(Element(page, "recovered", text, section, box(item, document)))
    return found


def elements(document: DoclingDocument, reread: Reread | None = None) -> list[Element]:
    """A Docling document's elements in reading order, text inside pictures (such as
    a drawing's callouts) included, each with the headings above it. `reread` reads
    a table again (from its image); where it gives None, Docling's reading stands."""
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
            rows = reread(item, tables, path) if reread else None
            found += table_rows(item, tables, path, document) if rows is None else rows
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

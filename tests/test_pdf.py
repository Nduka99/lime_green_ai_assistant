"""Reading PDFs into elements. The Docling documents here are built by hand, so no
model runs; every text is invented."""

from pathlib import Path
from typing import Any

import pytest
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.common.content_layer import ContentLayer
from docling_core.types.doc.common.reference import ProvenanceItem
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.key_value import GraphCell, GraphData
from docling_core.types.doc.items.table.table_data import TableCell, TableData
from docling_core.types.doc.labels import DocItemLabel, GraphCellLabel

from limespec import pdf
from limespec.elements import Element, row_text


def prov(page: int = 1, top: float = 700.0) -> ProvenanceItem:
    """A box 100 points wide and 20 high, `top` points above the page's bottom."""
    box = BoundingBox(
        l=50, t=top, r=150, b=top - 20, coord_origin=CoordOrigin.BOTTOMLEFT
    )
    return ProvenanceItem(page_no=page, bbox=box, charspan=(0, 1))


def cell(text: str, row: int, column: int, header: bool = False) -> TableCell:
    return TableCell(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=column,
        end_col_offset_idx=column + 1,
        column_header=header,
    )


def datasheet() -> DoclingDocument:
    """A two-page datasheet: title, sections, a list, a table with a two-row header
    and a blank corner, a drawing with a callout, a running footer."""
    doc = DoclingDocument(name="mortex")
    for page in (1, 2):
        doc.add_page(page_no=page, size=Size(width=600, height=800))
    doc.add_title(text="Mortex Mortar", prov=prov())
    doc.add_heading(text="Mixing", level=1, prov=prov(top=650))
    doc.add_text(
        label=DocItemLabel.TEXT, text="Add 4 litres of water.", prov=prov(top=620)
    )
    items = doc.add_list_group()
    doc.add_list_item(
        text="Mix for 3 minutes.",
        marker="1.",
        orig="1. Mix for 3 minutes.",
        parent=items,
        prov=prov(top=600),
    )
    doc.add_heading(text="Performance", level=1, prov=prov(top=560))
    cells = [
        cell("", 0, 0), cell("Grade", 0, 1, header=True),
        cell("Property", 1, 0, header=True), cell("M5", 1, 1, header=True),
        cell("Strength", 2, 0), cell("5 N/mm2", 2, 1),
        cell("Fire", 3, 0), cell("A1", 3, 1),
    ]  # fmt: skip
    caption = doc.add_text(
        label=DocItemLabel.CAPTION, text="Table 1", prov=prov(top=540)
    )
    doc.add_table(
        data=TableData(num_rows=4, num_cols=2, table_cells=cells),
        caption=caption,
        prov=prov(top=520),
    )
    doc.add_heading(text="Detail", level=2, prov=prov(page=2))
    drawing = doc.add_picture(prov=prov(page=2, top=600))
    doc.add_text(
        label=DocItemLabel.TEXT, text="Mesh here", prov=prov(2, 500), parent=drawing
    )
    doc.add_text(
        label=DocItemLabel.PAGE_FOOTER,
        text="Page 2 of 2",
        prov=prov(page=2, top=40),
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(label=DocItemLabel.TEXT, text="no position")  # no provenance
    doc.add_table(data=TableData(num_rows=0, num_cols=0), prov=prov(page=2, top=300))
    contents = TableData(
        num_rows=1, num_cols=2, table_cells=[cell("Mixing", 0, 0), cell("1", 0, 1)]
    )
    doc.add_table(
        data=contents, prov=prov(page=2, top=250), label=DocItemLabel.DOCUMENT_INDEX
    )
    pairs = [
        GraphCell(label=GraphCellLabel.KEY, cell_id=0, text="pH", orig="pH"),
        GraphCell(label=GraphCellLabel.VALUE, cell_id=1, text="11.2", orig="11.2"),
    ]
    doc.add_key_values(graph=GraphData(cells=pairs, links=[]), prov=prov(2, 200))
    return doc  # fmt: skip


def test_a_document_becomes_elements_in_reading_order() -> None:
    found = pdf.elements(datasheet())

    assert [(e.page, e.kind, e.text) for e in found] == [
        (1, "heading", "Mortex Mortar"),
        (1, "heading", "Mixing"),
        (1, "paragraph", "Add 4 litres of water."),
        (1, "list", "1. Mix for 3 minutes."),
        (1, "heading", "Performance"),
        (1, "caption", "Table 1"),
        (1, "table_header", "Property | Grade › M5"),
        (1, "table_row", "Table 1 › Strength — Grade › M5: 5 N/mm2"),
        (1, "table_row", "Table 1 › Fire — Grade › M5: A1"),
        (2, "heading", "Detail"),
        (2, "figure", ""),
        (2, "paragraph", "Mesh here"),
        (2, "furniture", "Page 2 of 2"),
        (2, "table_row", "Mixing — 1"),
        (2, "paragraph", "pH 11.2"),
    ]


def test_each_element_keeps_its_headings_box_and_cells() -> None:
    found = {e.text: e for e in pdf.elements(datasheet())}

    assert found["Add 4 litres of water."].section == ("Mortex Mortar", "Mixing")
    assert found["Mesh here"].section == ("Mortex Mortar", "Performance", "Detail")
    # 700 points above the bottom of an 800-point page is 100 from its top.
    assert found["Mortex Mortar"].bbox == (50.0, 100.0, 150.0, 120.0)
    row = found["Table 1 › Strength — Grade › M5: 5 N/mm2"]
    assert (row.table, row.row) == (1, 2)
    assert row.cells == (("Property", "Strength"), ("Grade › M5", "5 N/mm2"))
    assert found["Property | Grade › M5"].table == 1


def test_a_row_is_one_quotable_line() -> None:
    cells = (("Property", "Fire"), ("Class i", "A1"), ("", "EN 998"), ("Note", ""))

    assert row_text(cells) == "Fire — Class i: A1; EN 998"
    assert row_text((("", ""), ("Class i", "A1"))) == "Class i: A1"
    assert row_text((("Property", "Fire"),), "Table 2") == "Table 2 › Fire"


def test_a_pdf_is_read_through_the_converter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Converter:
        def convert(self, path: Path, page_range: tuple[int, int]) -> Any:
            calls.append((path, page_range))
            return type("Result", (), {"document": datasheet()})

    class Page:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def extract_text(self) -> str | None:
            return self.text

    class Reader:
        def __init__(self, path: Path) -> None:
            self.pages = [
                Page(None),
                Page("Detail\nA line the reading lost\nMesh here"),
            ]

    monkeypatch.setattr(pdf, "converter", Converter)
    monkeypatch.setattr(pdf, "PdfReader", Reader)

    found = pdf.read_pdf(Path("sheet.pdf"), first=2, last=2)

    assert calls == [(Path("sheet.pdf"), (2, 2))]
    assert all(isinstance(element, Element) for element in found)
    assert {element.page for element in found} == {2}
    assert found[-1] == Element(2, "recovered", "A line the reading lost")
    assert len(pdf.read_pdf(Path("sheet.pdf"))) == len(pdf.elements(datasheet())) + 1


def test_only_text_layer_lines_the_reading_lost_are_recovered() -> None:
    text_layer = (
        "Water absorption 0.8kg/(m2.min0.5) 1.0kg/(m2.min0.5)\n"
        "C E R T I F I C A T E\n"
        "noted in section 7 “Handling and storage”.\n"
        "  Additional Material (required if a WUFI Pro. Calculation)  "
    )
    parsed = (
        "Water absorption — Class i: 0.8kg/(m 2 .min 0.5 ); Class iii: 1.0kg/(m 2 "
        ".min 0.5 ) CERTIFICATE noted in section 7 'Handling and storage'."
    )

    assert pdf.lost_lines(text_layer, parsed) == [
        "Additional Material (required if a WUFI Pro. Calculation)"
    ]


def test_the_converter_reads_text_cells_without_ocr() -> None:
    options: Any = pdf.converter().format_to_options[InputFormat.PDF].pipeline_options

    assert options.do_ocr is False
    assert options.table_structure_options.mode.value == "accurate"

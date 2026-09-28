"""Recovering the words a page shows but Docling's reading lacks. Every page, line and
element here is invented; the PDFs are drawn by pdfium in the tests."""

import ctypes
from pathlib import Path
from typing import Any

import pypdfium2
import pypdfium2.raw as pdfium_c
import pytest
from PIL import Image

from limespec import recovery
from limespec.elements import Element

WHITE = 255


def page_image(ink: tuple[int, int, int, int] | None = None) -> Image.Image:
    """A 200 x 200 grey page (100 x 100 points at scale 2), with ink in one square."""
    image = Image.new("L", (200, 200), WHITE)
    if ink:
        image.paste(0, ink)
    return image


def test_words_are_compared_without_case_or_edge_marks_and_symbols_never() -> None:
    assert [recovery.key(word) for word in ("Mix,", "THEN", "(wait.)")] == [
        "mix",
        "then",
        "wait",
    ]
    assert recovery.key("•") == recovery.key("—") == ""


class TextPage:
    """Stands in for pdfium's text page: each character 1 point wide on one row."""

    def __init__(self, text: str) -> None:
        self.text = text

    def get_text_range(self) -> str:
        return self.text

    def get_charbox(self, index: int) -> tuple[float, float, float, float]:
        return (10.0 + index, 700.0, 11.0 + index, 710.0)


def test_each_word_gets_the_box_around_its_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery, "layer", lambda textpage, index: index == 0)

    lines = recovery.text_lines(
        TextPage("Ab\r\n  \r\ncd\t e\r\nself\ufffedeclared"), height=800
    )

    # "Ab" is characters 0-1, "cd" 8-9, "e" 12, "self-declared" 15-27.
    assert lines == [
        [("Ab", (10.0, 90.0, 12.0, 100.0), True)],
        [("cd", (18.0, 90.0, 20.0, 100.0), False),
         ("e", (22.0, 90.0, 23.0, 100.0), False)],
        [("self-declared", (25.0, 90.0, 38.0, 100.0), False)],
    ]  # fmt: skip


def test_a_word_is_visible_where_its_text_draws_or_a_layer_has_ink() -> None:
    inked = page_image(ink=(20, 20, 31, 31))
    drawn_text = (inked, page_image(ink=(20, 20, 31, 31)).point(lambda v: 255 - v))
    no_text = (inked, page_image().point(lambda v: 0))

    assert recovery.visible(("a", (10, 10, 15, 15), False), (100, 100), drawn_text)
    assert not recovery.visible(("a", (10, 10, 15, 15), False), (100, 100), no_text)
    assert recovery.visible(("a", (10, 10, 15, 15), True), (100, 100), no_text)
    assert not recovery.visible(("a", (40, 40, 45, 45), True), (100, 100), no_text)
    below = ("a", (10.0, 120.0, 15.0, 130.0), True)
    assert not recovery.visible(below, (100, 100), drawn_text)  # off the page
    # On a 100 x 150 page whose drawing ends at 100 points: nothing to look at.
    assert not recovery.visible(below, (100, 150), drawn_text)


def element(
    kind: str, text: str, box: tuple[float, ...] | None, section: str = ""
) -> Element:
    return Element(1, kind, text, (section,) if section else (), box)  # type: ignore[arg-type]


def test_a_recovered_line_goes_below_its_neighbour_in_its_column() -> None:
    placed = [
        element("heading", "Mixing", (10, 10, 90, 20), "Mixing"),
        element("table_row", "row 1", (10, 30, 90, 60), "Mixing"),
        element("table_row", "row 2", (10, 30, 90, 60), "Mixing"),
        element("paragraph", "side note", (200, 30, 300, 40), "Notes"),
    ]

    after_table = recovery.anchor(placed, (10, 70, 50, 80))
    above_all = recovery.anchor(placed[1:], (10, 0, 50, 5))
    elsewhere = recovery.anchor(placed, (400, 70, 450, 80))

    assert after_table == (3, ("Mixing",))  # after the table's last row
    assert above_all == (0, ("Mixing",))  # before the first element below it
    assert elsewhere == (4, ())  # no element in its column: the page's end
    assert recovery.anchor([element("figure", "", None)], (0, 0, 1, 1)) == (1, ())


def line(text: str, top: float, left: float = 10.0) -> Any:
    """A pdfium line of 10-point-wide words, 12 points apart, starting at `left`."""
    return [
        (word, (left + 12 * i, top, left + 12 * i + 10, top + 5), False)
        for i, word in enumerate(text.split())
    ]


def test_a_page_recovers_the_words_it_shows_and_counts_the_rest() -> None:
    found = [
        element("heading", "Mixing", (10, 10, 90, 20), "Mixing"),
        element("paragraph", "Water absorption 0.8kg/(m 2 .min 0.5 )", (10, 25, 90, 35),
                "Mixing"),
    ]  # fmt: skip
    lines = [
        line("• Water absorption 0.8kg/(m2.min0.5)", 25),  # the bullet is not compared
        line("Mix for three minutes", 40),
        line("Contractor to report errors", 120),  # off the page
        line("Clipped note here", 60, left=-26),  # drawn nowhere a reader sees
    ]
    drawn = []

    def draw() -> Any:
        drawn.append(1)
        text = page_image(ink=(20, 80, 120, 90)).point(lambda v: 255 - v)
        return page_image(ink=(0, 110, 200, 130)), text  # a frame line crosses the note

    placed, check = recovery.recover_page(1, found, lines, (100, 100), draw)

    assert [e.text for e in placed] == [
        "Mixing",
        "Water absorption 0.8kg/(m 2 .min 0.5 )",
        "Mix for three minutes",
    ]
    assert placed[2] == Element(1, "recovered", "Mix for three minutes", ("Mixing",),
                                (10.0, 40.0, 56.0, 45.0))  # fmt: skip
    assert check == {"words": 7, "kept": 4, "hidden": 7, "recovered": 1}
    assert drawn == [1]  # drawn once, and only because a line was missing
    recovery.recover_page(1, found, lines[:1], (100, 100), draw)
    assert drawn == [1]


def text_object(document: Any, text: str, x: float, y: float) -> Any:
    """A line of 12-point Helvetica placed at (x, y) from the bottom-left."""
    font = pdfium_c.FPDFText_LoadStandardFont(document, b"Helvetica")
    made = pdfium_c.FPDFPageObj_CreateTextObj(document, font, 12.0)
    encoded = ctypes.create_string_buffer((text + "\x00").encode("utf-16-le"))
    pdfium_c.FPDFText_SetText(made, ctypes.cast(encoded, pdfium_c.FPDF_WIDESTRING))
    pdfium_c.FPDFPageObj_Transform(made, 1, 0, 0, 1, x, y)
    return made


def rectangle(x: float, y: float, width: float, height: float, grey: int) -> Any:
    """A filled grey rectangle."""
    made = pdfium_c.FPDFPageObj_CreateNewRect(x, y, width, height)
    pdfium_c.FPDFPageObj_SetFillColor(made, grey, grey, grey, 255)
    pdfium_c.FPDFPath_SetDrawMode(made, pdfium_c.FPDF_FILLMODE_WINDING, False)
    return made


def sheet(path: Path) -> None:
    """A two-page PDF, 200 x 200 points. Page 2 holds text a reader sees, an invisible
    text layer over a black box, text under a white box and text off the page."""
    document = pypdfium2.PdfDocument.new()
    cover = document.new_page(200, 200)
    pdfium_c.FPDFPage_InsertObject(cover, text_object(document, "Cover", 10, 170))
    pdfium_c.FPDFPage_GenerateContent(cover)
    page = document.new_page(200, 200)
    layer = text_object(document, "Gamma delta", 10, 122)
    pdfium_c.FPDFTextObj_SetTextRenderMode(
        layer, pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE
    )
    for made in (
        text_object(document, "Alpha beta", 10, 170),
        rectangle(8, 118, 90, 16, 0),
        layer,
        text_object(document, "Epsilon zeta", 10, 80),
        rectangle(5, 70, 150, 25, 255),
        text_object(document, "Kappa omega", -150, 40),
    ):
        pdfium_c.FPDFPage_InsertObject(page, made)
    pdfium_c.FPDFPage_GenerateContent(page)
    document.save(path)
    document.close()


def test_a_layer_is_invisible_text_or_a_type_3_font(tmp_path: Path) -> None:
    sheet(tmp_path / "sheet.pdf")
    document = pypdfium2.PdfDocument(tmp_path / "sheet.pdf")
    textpage = document[1].get_textpage()
    text = textpage.get_text_range()

    assert not recovery.layer(textpage, text.index("Alpha"))
    assert recovery.layer(textpage, text.index("Gamma"))
    textpage.close()
    document.close()


def test_a_document_s_pages_are_recovered_in_range(tmp_path: Path) -> None:
    sheet(tmp_path / "sheet.pdf")
    found = [Element(2, "paragraph", "Alpha beta", (), (10, 18, 70, 30))]
    checks: dict[int, dict[str, int]] = {}

    ordered = recovery.recover(tmp_path / "sheet.pdf", found, 2, 2, checks)

    assert [(e.page, e.kind, e.text) for e in ordered] == [
        (2, "paragraph", "Alpha beta"),
        (2, "recovered", "Gamma delta"),
    ]
    assert checks == {2: {"words": 4, "kept": 2, "hidden": 4, "recovered": 1}}
    assert len(recovery.recover(tmp_path / "sheet.pdf", found, 1, 2)) == 3

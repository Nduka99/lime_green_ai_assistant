"""Recovering the lines a page shows but Docling's reading lacks. Every page, line and
element here is invented; pdfium is replaced by stand-ins."""

from pathlib import Path
from typing import Any

import pypdfium2
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


def test_words_are_compared_without_spacing_case_or_edge_marks() -> None:
    assert recovery.words("Mix, THEN  wait. —") == ["mix", "then", "wait"]


class TextPage:
    """Stands in for pdfium's text page: each character 1 point wide on one row."""

    def __init__(self, text: str) -> None:
        self.text = text

    def get_text_range(self) -> str:
        return self.text

    def get_charbox(self, index: int) -> tuple[float, float, float, float]:
        return (10.0 + index, 700.0, 11.0 + index, 710.0)


def test_each_line_gets_the_box_around_its_characters() -> None:
    lines = recovery.text_lines(TextPage("Ab\r\n  \r\ncd\t e\r\n"), height=800)

    # "Ab" is characters 0-1; "cd\t e" is 8-12 (spacing is not measured).
    assert lines == [
        ("Ab", (10.0, 90.0, 12.0, 100.0)),
        ("cd e", (18.0, 90.0, 23.0, 100.0)),
    ]


def test_text_is_shown_when_it_lies_on_the_page_with_ink() -> None:
    inked = page_image(ink=(20, 20, 31, 31))

    assert recovery.shown((10, 10, 15, 15), 100, 100, inked)
    assert not recovery.shown((40, 40, 45, 45), 100, 100, inked)  # white there
    assert not recovery.shown((10, 120, 15, 130), 100, 100, inked)  # below the page
    # On a 100 x 150 page whose drawing ends at 100 points: nothing to look at.
    assert not recovery.shown((10, 120, 15, 130), 100, 150, page_image())


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


def test_a_page_recovers_the_lines_it_shows_and_counts_the_rest() -> None:
    found = [
        element("heading", "Mixing", (10, 10, 90, 20), "Mixing"),
        element("paragraph", "Water absorption 0.8kg/(m 2 .min 0.5 )", (10, 25, 90, 35),
                "Mixing"),
    ]  # fmt: skip
    lines = [
        ("Water absorption 0.8kg/(m2.min0.5)", (10.0, 25.0, 90.0, 35.0)),
        ("Mix for three minutes", (10.0, 40.0, 60.0, 45.0)),
        ("Contractor to report errors", (10.0, 120.0, 60.0, 125.0)),  # off the page
    ]
    drawn = []

    def draw() -> Image.Image:
        drawn.append(1)
        return page_image(ink=(20, 80, 120, 90))

    placed, check = recovery.recover_page(1, found, lines, (100, 100), draw)

    assert [e.text for e in placed] == [
        "Mixing",
        "Water absorption 0.8kg/(m 2 .min 0.5 )",
        "Mix for three minutes",
    ]
    assert placed[2] == Element(1, "recovered", "Mix for three minutes", ("Mixing",),
                                (10.0, 40.0, 60.0, 45.0))  # fmt: skip
    assert check == {"words": 7, "kept": 4, "hidden": 4, "recovered": 1}
    assert drawn == [1]  # drawn once, and only because a line was missing
    recovery.recover_page(1, found, lines[:1], (100, 100), draw)
    assert drawn == [1]


class Page:
    """Stands in for a pdfium page: 100 x 100 points, one line, ink everywhere."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.closed = False

    def get_size(self) -> tuple[float, float]:
        return (100.0, 100.0)

    def get_textpage(self) -> Any:
        page = TextPage(self.text)
        page.get_charbox = lambda index: (10.0, 50.0, 20.0, 60.0)  # type: ignore[method-assign]
        page.close = lambda: None  # type: ignore[attr-defined]
        return page

    def render(self, scale: float) -> Any:
        assert scale == recovery.SCALE
        image = page_image(ink=(0, 0, 200, 200))
        return type("Bitmap", (), {"to_pil": lambda self: image})()

    def close(self) -> None:
        self.closed = True


class Document:
    """Stands in for a pdfium document of three one-line pages."""

    opened: list["Document"] = []

    def __init__(self, path: Path) -> None:
        self.pages = [Page("Title"), Page("Kept words"), Page("Lost words here")]
        self.closed = False
        Document.opened.append(self)

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> Page:
        return self.pages[index]

    def close(self) -> None:
        self.closed = True


def test_a_document_s_pages_are_recovered_in_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pypdfium2, "PdfDocument", Document)
    found = [Element(2, "paragraph", "Kept words", (), (10, 30, 20, 45))]
    checks: dict[int, dict[str, int]] = {}

    ordered = recovery.recover(Path("sheet.pdf"), found, 2, 3, checks)

    assert [(e.page, e.kind, e.text) for e in ordered] == [
        (2, "paragraph", "Kept words"),
        (3, "recovered", "Lost words here"),
    ]
    assert checks == {
        2: {"words": 2, "kept": 2, "hidden": 0, "recovered": 0},
        3: {"words": 3, "kept": 0, "hidden": 0, "recovered": 1},
    }
    document = Document.opened[-1]
    assert document.closed and document.pages[1].closed and document.pages[2].closed
    assert not document.pages[0].closed  # page 1 was not read
    recovery.recover(Path("sheet.pdf"), found, 2, 2)  # checks are optional

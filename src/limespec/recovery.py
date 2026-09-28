"""Text Docling's reading lacks, recovered from pdfium where the page shows it.

docling-parse extracts no characters for some text pdfium reads: Type 3 fonts,
some running headers (measured in X8's follow-ups: 930 visible words over the
corpus). Each pdfium line holding a word the page's elements lack is recovered only
if the page shows it: its box lies on the page and the drawn page has ink there. A
CAD title block placed off the page (469 words) is therefore never indexed. A
recovered line goes after the element nearest above it in its column, in that
element's section.

Imported only when a PDF is read, so the API never needs the `ingest` group.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from limespec.elements import Element
from limespec.pdf import EDGES, squash

Box = tuple[float, float, float, float]  # left, top, right, bottom from the top-left
Line = tuple[str, Box]
INK = 200  # a grey level (0 black, 255 white) darker than this is ink
SCALE = 2.0  # pages are drawn at 144 DPI to look for ink
LINE_END_HYPHEN = "￾"  # how pdfium writes a hyphen that ends a line it joins


def words(text: str) -> list[str]:
    """The text's words for comparison: no spacing, case, typography or edge marks."""
    return [
        word for word in (squash(part).strip(EDGES) for part in text.split()) if word
    ]


def text_lines(textpage: Any, height: float) -> list[Line]:
    """The page's text as pdfium reads it, one line per line break with its spacing
    (tabs included) made single spaces, each with the box around its characters
    (measured from the page's top-left corner). pdfium joins a line ending in a
    hyphen to the next; the hyphen is written back as the page shows it."""
    text = textpage.get_text_range().replace(LINE_END_HYPHEN, "-")
    lines = []
    for match in re.finditer(r"[^\r\n]+", text):
        span = range(match.start(), match.end())
        boxes = [textpage.get_charbox(i) for i in span if not text[i].isspace()]
        if not boxes:
            continue
        left = min(box[0] for box in boxes)
        bottom = min(box[1] for box in boxes)
        right = max(box[2] for box in boxes)
        top = max(box[3] for box in boxes)
        lines.append(
            (
                " ".join(match.group().split()),
                (left, height - top, right, height - bottom),
            )
        )
    return lines


def shown(box: Box, width: float, height: float, image: Any) -> bool:
    """Whether a reader sees the text in `box`: its centre lies on the page and the
    drawn page (grey, at SCALE) has ink inside it."""
    left, top, right, bottom = box
    if not (0 <= (left + right) / 2 <= width and 0 <= (top + bottom) / 2 <= height):
        return False
    area = (
        max(0, int(left * SCALE)),
        max(0, int(top * SCALE)),
        min(image.width, int(right * SCALE) + 1),
        min(image.height, int(bottom * SCALE) + 1),
    )
    if area[0] >= area[2] or area[1] >= area[3]:
        return False
    darkest, _ = image.crop(area).getextrema()
    return bool(darkest < INK)


def anchor(placed: list[Element], box: Box) -> tuple[int, tuple[str, ...]]:
    """Where a recovered line goes: after the element nearest above it that overlaps it
    horizontally, else before the nearest such element below it, else at the page's
    end. Its section is that element's."""
    left, top, right, bottom = box
    middle = (top + bottom) / 2
    above = []
    below = []
    for index, element in enumerate(placed):
        if element.bbox is None:
            continue
        e_left, e_top, e_right, e_bottom = element.bbox
        if e_left >= right or left >= e_right:
            continue  # another column
        centre = (e_top + e_bottom) / 2
        if centre <= middle:
            above.append((centre, index))
        else:
            below.append((centre, index))
    if above:
        _, index = max(above)  # the lowest above, the last of equals (a table's rows)
        return index + 1, placed[index].section
    if below:
        _, index = min(below)  # the highest below, the first of equals
        return index, placed[index].section
    return len(placed), ()


def recover_page(
    number: int,
    elements: list[Element],
    lines: list[Line],
    size: tuple[float, float],
    draw: Callable[[], Any],
) -> tuple[list[Element], dict[str, int]]:
    """The page's elements with every shown line they lack placed where it stands,
    and the page's check: pdfium words a reader sees, how many of them the parser's
    own reading holds, words not shown, and lines recovered."""
    width, height = size
    have = squash(" ".join(element.text for element in elements))
    image = None
    seen = kept = hidden = 0
    lost = []
    for text, box in lines:
        found = words(text)
        missing = [word for word in found if word not in have]
        if missing:
            image = draw() if image is None else image
            if shown(box, width, height, image):
                lost.append((text, box))
            else:
                hidden += len(missing)
                found = [word for word in found if word in have]
                missing = []
        seen += len(found)
        kept += len(found) - len(missing)
    placed = list(elements)
    for text, box in sorted(lost, key=lambda line: (line[1][1], line[1][0])):
        index, section = anchor(placed, box)
        placed.insert(index, Element(number, "recovered", text, section, box))
    check = {"words": seen, "kept": kept, "hidden": hidden, "recovered": len(lost)}
    return placed, check


def recover(
    path: Path,
    found: list[Element],
    first: int,
    last: int,
    checks: dict[int, dict[str, int]] | None = None,
) -> list[Element]:
    """Pages `first` to `last` in reading order, each with its shown lines recovered;
    `checks` receives each page's check."""
    import pypdfium2
    from docling.utils.locks import pypdfium2_lock

    ordered = []
    with pypdfium2_lock:
        document = pypdfium2.PdfDocument(path)
        try:
            pages = {element.page for element in found} | set(
                range(first, len(document) + 1)
            )
            for number in sorted(n for n in pages if first <= n <= last):
                page = document[number - 1]
                width, height = page.get_size()
                textpage = page.get_textpage()
                lines = text_lines(textpage, height)
                textpage.close()

                def draw(page: Any = page) -> Any:
                    return page.render(scale=SCALE).to_pil().convert("L")

                on_page = [element for element in found if element.page == number]
                placed, check = recover_page(
                    number, on_page, lines, (width, height), draw
                )
                page.close()
                ordered += placed
                if checks is not None:
                    checks[number] = check
        finally:
            document.close()
    return ordered

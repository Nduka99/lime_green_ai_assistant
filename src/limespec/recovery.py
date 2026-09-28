"""Text Docling's reading lacks, recovered from pdfium where the page shows it.

docling-parse extracts no characters for some text pdfium reads: Type 3 fonts,
some running headers (measured in X8's follow-ups: 930 visible words over the
corpus). Each pdfium line holding a word the page's elements lack is recovered with
only the words a reader sees (X8 report, second amendment): a word is visible when
its centre lies on the page and drawing its text changes the page there; text that
draws nothing itself (invisible text, Type 3 layers over outlines) is visible where
the page has ink. Text clipped out of view or placed off the page is never indexed. A
recovered line goes after the element nearest above it in its column, in that
element's section.

Imported only when a PDF is read, so the API never needs the `ingest` group.
"""

import re
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pypdfium2
import pypdfium2.raw as pdfium_c
from docling.utils.locks import pypdfium2_lock
from PIL import ImageChops

from limespec.elements import Element
from limespec.pdf import EDGES, squash

Box = tuple[float, float, float, float]  # left, top, right, bottom from the top-left
Word = tuple[str, Box, bool]  # text, box, and whether its text is a layer (`layer`)
Line = list[Word]
Images = tuple[Any, Any]  # the drawn page, and what its text draws (`drawings`)
INK = 200  # a grey level (0 black, 255 white) darker than this is ink
SCALE = 2.0  # pages are drawn at 144 DPI
LINE_END_HYPHEN = "￾"  # how pdfium writes a hyphen that ends a line it joins


def key(word: str) -> str:
    """A word as compared with the reading: no spacing, case, typography or edge
    marks. Empty unless it holds a letter or a digit, so bullets are never compared."""
    folded = squash(word).strip(EDGES)
    return folded if any(char.isalnum() for char in folded) else ""


def around(boxes: list[Box]) -> Box:
    """The box around several boxes."""
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def layer(textpage: Any, index: int) -> bool:
    """Whether the character's text draws nothing itself, being a layer over another
    rendition of it (outlines, a scan): invisible text, or a Type 3 font, the only
    font type with no BaseFont (PDF 32000-1, 9.6.5)."""
    text_object = pdfium_c.FPDFText_GetTextObject(textpage, index)
    mode = pdfium_c.FPDFTextObj_GetTextRenderMode(text_object)
    if mode == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
        return True
    font = pdfium_c.FPDFTextObj_GetFont(text_object)
    return bool(pdfium_c.FPDFFont_GetBaseFontName(font, None, 0) <= 1)  # "" and NUL


def text_lines(textpage: Any, height: float) -> list[Line]:
    """The page's words as pdfium reads them, line by line, each with the box around
    its characters (from the page's top-left corner) and whether it is a layer.
    pdfium joins a line ending in a hyphen to the next; the hyphen is written back as
    the page shows it."""
    text = textpage.get_text_range().replace(LINE_END_HYPHEN, "-")
    lines = []
    for line in re.finditer(r"[^\r\n]+", text):
        found = []
        for match in re.finditer(r"\S+", line.group()):
            start = line.start() + match.start()
            chars = [
                textpage.get_charbox(i) for i in range(start, start + len(match[0]))
            ]
            left = min(char[0] for char in chars)
            bottom = min(char[1] for char in chars)
            right = max(char[2] for char in chars)
            top = max(char[3] for char in chars)
            box = (left, height - top, right, height - bottom)
            found.append((match[0], box, layer(textpage, start)))
        if found:
            lines.append(found)
    return lines


def drawings(page: Any) -> Images:
    """The page drawn in grey at SCALE, and what its text draws on it: the difference
    from the page drawn with every text object invisible (the page is changed)."""
    drawn = page.render(scale=SCALE).to_pil().convert("L")
    for text_object in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT]):
        pdfium_c.FPDFTextObj_SetTextRenderMode(
            text_object, pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE
        )
    bare = page.render(scale=SCALE).to_pil().convert("L")
    return drawn, ImageChops.difference(drawn, bare)


def visible(word: Word, size: tuple[float, float], images: Images) -> bool:
    """Whether a reader sees the word: its centre lies on the page, and its text
    changes the drawn page inside its box, or (a layer) the page has ink there."""
    _, (left, top, right, bottom), is_layer = word
    width, height = size
    if not (0 <= (left + right) / 2 <= width and 0 <= (top + bottom) / 2 <= height):
        return False
    drawn, text = images
    area = (
        max(0, int(left * SCALE)),
        max(0, int(top * SCALE)),
        min(drawn.width, int(right * SCALE) + 1),
        min(drawn.height, int(bottom * SCALE) + 1),
    )
    if area[0] >= area[2] or area[1] >= area[3]:
        return False
    _, change = text.crop(area).getextrema()
    if change > 0:
        return True
    darkest, _ = drawn.crop(area).getextrema()
    return is_layer and darkest < INK


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
    draw: Callable[[], Images],
) -> tuple[list[Element], dict[str, int]]:
    """The page's elements with the visible words of every line they lack placed
    where the line stands, and the page's check: pdfium words a reader sees, how many
    of them the parser's own reading holds, words it lacks that are not shown, and
    lines recovered."""
    have = squash(" ".join(element.text for element in elements))
    images = None
    seen = kept = hidden = 0
    lost = []
    for line in lines:
        compared = [word for word in line if key(word[0])]
        missing = [word for word in compared if key(word[0]) not in have]
        unseen = []
        if missing:
            images = draw() if images is None else images
            shown = [word for word in line if visible(word, size, images)]
            unseen = [word for word in missing if word not in shown]
            if len(unseen) < len(missing):
                lost.append(shown)
        hidden += len(unseen)
        seen += len(compared) - len(unseen)
        kept += len(compared) - len(missing)
    placed = list(elements)
    recovered = []
    for words in lost:
        box = around([word[1] for word in words])
        recovered.append((box[1], box[0], " ".join(word[0] for word in words), box))
    for _, _, text, box in sorted(recovered):  # top to bottom, then left to right
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
    """Pages `first` to `last` in reading order, each with its lost visible words
    recovered; `checks` receives each page's check."""
    ordered = []
    with pypdfium2_lock:
        document = pypdfium2.PdfDocument(path)
        try:
            pages = {element.page for element in found} | set(
                range(first, len(document) + 1)
            )
            for number in sorted(n for n in pages if first <= n <= last):
                page = document[number - 1]
                textpage = page.get_textpage()
                lines = text_lines(textpage, page.get_height())
                textpage.close()
                on_page = [element for element in found if element.page == number]
                placed, check = recover_page(
                    number, on_page, lines, page.get_size(), partial(drawings, page)
                )
                page.close()
                ordered += placed
                if checks is not None:
                    checks[number] = check
        finally:
            document.close()
    return ordered

"""Images as the index keeps them (X43 B).

Every picture is stored once as a PNG whose longest side is at most MAX_SIDE pixels:
the format llama.cpp's image loader reads (it does not read WebP, the format of most
of the site's images). A PDF figure is cut from its page by pdfium at its box, as
`rendering` draws pages. Used when building an index, never by the API, so it needs
the `ingest` group.
"""

import hashlib
from io import BytesIO
from pathlib import Path

import pypdfium2
from PIL import Image

MAX_SIDE = 1024  # pixels: the longest side of a stored image
FIGURE_SCALE = 200 / 72  # a figure is drawn at 200 DPI, as tables are read (pdf.py)
Box = tuple[float, float, float, float]  # left, top, right, bottom, from top-left


def normalised(data: bytes) -> bytes:
    """The image as an RGB PNG at most MAX_SIDE pixels on its longest side; any
    transparency is laid on white. Raises PIL.UnidentifiedImageError for a format PIL
    cannot read (SVG)."""
    with Image.open(BytesIO(data)) as opened:
        opened.load()
        image = opened.convert("RGBA")
    flat = Image.new("RGB", image.size, "white")
    flat.paste(image, mask=image.getchannel("A"))
    flat.thumbnail((MAX_SIDE, MAX_SIDE))
    out = BytesIO()
    flat.save(out, format="PNG")
    return out.getvalue()


def image_id(png: bytes) -> str:
    """A stored image's id: the SHA-256 of its PNG."""
    return hashlib.sha256(png).hexdigest()


def crop(pdf: Path, page: int, box: Box) -> bytes:
    """A figure's picture as PNG bytes: page `page` (from 1) drawn by pdfium at
    FIGURE_SCALE and cut at `box`, in points from the page's top-left corner."""
    document = pypdfium2.PdfDocument(str(pdf))
    try:
        drawn = document[page - 1]
        width, height = drawn.get_size()
        left, top, right, bottom = box
        margins = (left, height - bottom, width - right, top)
        bitmap = drawn.render(scale=FIGURE_SCALE, crop=margins)
        out = BytesIO()
        bitmap.to_pil().save(out, format="PNG")
        bitmap.close()
    finally:
        document.close()
    return normalised(out.getvalue())

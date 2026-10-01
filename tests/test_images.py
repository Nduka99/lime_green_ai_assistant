"""Images as the index keeps them (X43 B). Invented images and a blank PDF."""

from io import BytesIO
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image, UnidentifiedImageError

from limespec import images


def encoded(image: Image.Image, form: str) -> bytes:
    out = BytesIO()
    image.save(out, format=form)
    return out.getvalue()


def test_an_image_is_stored_as_an_rgb_png_at_most_max_side() -> None:
    wide = encoded(Image.new("RGB", (3000, 1000), "green"), "WEBP")
    clear = encoded(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")

    stored = Image.open(BytesIO(images.normalised(wide)))
    flat = Image.open(BytesIO(images.normalised(clear)))

    assert (stored.format, stored.mode, stored.size) == ("PNG", "RGB", (1024, 341))
    assert flat.getpixel((0, 0)) == (255, 255, 255)  # transparency laid on white
    assert images.image_id(b"png") == images.image_id(b"png") != images.image_id(b"x")
    with pytest.raises(UnidentifiedImageError):
        images.normalised(b"<svg xmlns='http://www.w3.org/2000/svg'/>")


def test_a_figure_is_cut_from_its_page_at_its_box(tmp_path: Path) -> None:
    document = pypdfium2.PdfDocument.new()
    document.new_page(200, 100)
    path = tmp_path / "sheet.pdf"
    document.save(str(path))
    document.close()

    figure = Image.open(BytesIO(images.crop(path, 1, (10, 10, 110, 60))))

    # 100 x 50 points drawn at 200 DPI: 277.8 x 138.9 pixels, which pdfium truncates
    assert figure.size == (277, 138) or figure.size == (278, 138)

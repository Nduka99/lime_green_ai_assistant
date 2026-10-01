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
    icon = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    icon.putpixel((5, 5), (255, 255, 255, 255))  # a white drawing on transparency
    shown = Image.open(BytesIO(images.normalised(encoded(icon, "PNG"))))
    assert shown.getpixel((0, 0)) == images.DARK_GROUND
    assert shown.getpixel((5, 5)) == (255, 255, 255)
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


PAGE = """<html><body><main><h1>Duro</h1>
<h2>Colours</h2><div class="clr-grid">
<a class="clr"><img data-src="/images/york.webp"><p class="name">York</p></a></div>
<p>Text <img src="/images/wall.png" alt="A wall pointed with lime mortar"></p>
<img src="/images/logo.svg" alt="">
<img src="/images/gone.png" alt="gone">
</main></body></html>"""


def test_every_image_of_a_page_and_every_figure_of_a_document_is_stored_once(
    tmp_path: Path,
) -> None:
    from limespec import config

    picture = encoded(Image.new("RGB", (40, 20), "green"), "WEBP")
    (tmp_path / "york.webp").write_bytes(picture)
    (tmp_path / "wall.png").write_bytes(picture)  # the same picture twice
    (tmp_path / "logo.svg").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    document = pypdfium2.PdfDocument.new()
    document.new_page(200, 200)
    document.save(str(tmp_path / "sheet.pdf"))
    document.close()
    site = config.SITE
    stored = {
        site + "images/york.webp": tmp_path / "york.webp",
        site + "images/wall.png": tmp_path / "wall.png",
        site + "images/logo.svg": tmp_path / "logo.svg",
        site + "sheet.pdf": tmp_path / "sheet.pdf",
    }
    figure = {"kind": "figure", "page": 1, "text": "Fig 1", "section": ["Build-up"],
              "bbox": [10, 10, 110, 110]}  # fmt: skip
    small = figure | {"bbox": [0, 0, 20, 20]}
    text = {"kind": "paragraph", "page": 1, "text": "Mix", "section": [], "bbox": None}
    reading = {"urls": [site + "sheet.pdf"], "elements": [figure, small, text]}

    places = images.collect({site + "duro": PAGE}, [reading], stored, tmp_path / "out")

    assert [(p["alt"], p["source"], p["page"], p["section"]) for p in places] == [
        ("York", site + "duro", None, ["Colours"]),
        ("A wall pointed with lime mortar", site + "duro", None, ["Colours"]),
        ("Fig 1", site + "sheet.pdf", 1, ["Build-up"]),
    ]
    assert places[0]["id"] == places[1]["id"]  # one stored file for both
    assert len(list((tmp_path / "out").glob("*.png"))) == 2

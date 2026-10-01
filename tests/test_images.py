"""Images as the index keeps them (X43 B). Invented images and a blank PDF."""

from io import BytesIO
from pathlib import Path
from typing import Any

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


def test_each_picture_becomes_one_passage_of_its_own_words() -> None:
    site = "https://x.test/"
    places: list[dict[str, Any]] = [
        {"id": "p1", "source": site + "duro", "page": None, "alt": "York",
         "section": ["Colours"]},
        {"id": "p1", "source": site + "york", "page": None, "alt": "",
         "section": []},
        {"id": "p2", "source": site + "sheet.pdf", "page": 2,
         "alt": "A wall pointed with lime mortar", "section": ["Build-up"]},
        {"id": "p3", "source": site + "duro", "page": None, "alt": "Duro bag",
         "section": []},
    ]  # fmt: skip
    read = {
        "p2": "Solo 2nd pass\n\n<b>Duro</b> $25\\mathrm{kg}$",
        "p3": "Duro\nlime green",  # all of it shown on its page already
    }
    shown: dict[tuple[str, int | None], str] = {
        (site + "duro", None): "Duro lime green base coat"
    }
    titles = {site + "duro": "Duro", site + "sheet.pdf": "Duro — Data Sheet"}

    found = images.picture_passages(places, read, shown, titles)

    assert found == [
        ((site + "duro", "Duro", "Image", "", "Image › Colours › York", None), "p1"),
        (
            (site + "sheet.pdf", "Duro — Data Sheet", "Image",
             "A wall pointed with lime mortar\nSolo 2nd pass\nDuro 25kg",
             "Image › Build-up", 2),
            "p2",
        ),
        ((site + "duro", "Duro", "Image", "", "Image › Duro bag", None), "p3"),
    ]  # fmt: skip
    assert images.new_words("", "x") == 0.0


@pytest.mark.parametrize(("finish", "found"), [("stop", "Duro 25kg"), ("length", "")])
def test_only_a_reading_the_model_finished_is_text(
    monkeypatch: pytest.MonkeyPatch, finish: str, found: str
) -> None:
    import httpx

    from limespec import llm

    sent: list[Any] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append((url, kwargs["json"]))
        choice = {"finish_reason": finish, "message": {"content": "Duro 25kg"}}
        return httpx.Response(
            200, json={"choices": [choice]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(llm.CLIENT, "post", post)

    assert images.read_text(Image.new("RGB", (4, 4)), "http://vlm") == found
    url, body = sent[0]
    assert url == "http://vlm/v1/chat/completions"
    assert body["messages"][0]["content"][1]["text"] == "Text Recognition:"


def test_a_failed_reading_is_a_model_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from limespec import llm

    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.CLIENT, "post", post)

    with pytest.raises(llm.ModelServerError):
        images.read_text(Image.new("RGB", (4, 4)), "http://vlm")

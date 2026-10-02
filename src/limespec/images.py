"""Images as the index keeps them (X43 B).

Every picture is stored once as a PNG whose longest side is at most MAX_SIDE pixels:
the format llama.cpp's image loader reads (it does not read WebP, the format of most
of the site's images). A PDF figure is cut from its page by pdfium at its box, as
`rendering` draws pages. Used when building an index, never by the API, so it needs
the `ingest` group.
"""

import base64
import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pypdfium2
from PIL import Image, ImageStat, UnidentifiedImageError

from limespec import config, llm, webpage

MAX_SIDE = 1024  # pixels: the longest side of a stored image
LIGHT = 200  # mean grey level above which drawn pixels count as light
DARK_GROUND = (51, 51, 51)  # laid under light drawings (the site's dark grey)
MIN_SIDE = 72  # points: a smaller PDF figure is a mark, not a picture
DESCRIBED = 5  # words: an alt text this long describes its picture (X42)
# The share of read words a page must lack for the text read in a picture to be kept
# (X43 B2): a pack shot repeating its page's product name adds nothing.
NEW_WORDS = 0.2
PICTURE = "Image"  # the heading of a passage made from a picture
WORD = re.compile(r"\w+")
TAG = re.compile(r"<[^>]+>")
FIGURE_SCALE = 200 / 72  # a figure is drawn at 200 DPI, as tables are read (pdf.py)
OCR_PROMPT = "Text Recognition:"  # GLM-OCR's prompt for the text in an image
OCR_MAX_TOKENS = 8192  # GLM-OCR's published limit
OCR_TIMEOUT_SECONDS = 600.0
# A line of markup alone: a code fence (with its language) or a horizontal rule.
MARKUP_LINE = re.compile(r"```\w*|[-*_=]{3,}")
Box = tuple[float, float, float, float]  # left, top, right, bottom, from top-left


def normalised(data: bytes) -> bytes:
    """The image as an RGB PNG at most MAX_SIDE pixels on its longest side. Any
    transparency is laid on a ground that contrasts with what is drawn: dark under a
    light drawing (the site's white icons and lettering), white otherwise. Raises
    PIL.UnidentifiedImageError for a format PIL cannot read (SVG)."""
    with Image.open(BytesIO(data)) as opened:
        opened.load()
        image = opened.convert("RGBA")
    drawn = image.getchannel("A").point(lambda alpha: 255 if alpha > 128 else 0)
    level = (
        ImageStat.Stat(image.convert("L"), mask=drawn).mean[0] if drawn.getbbox() else 0
    )
    flat = Image.new("RGB", image.size, DARK_GROUND if level > LIGHT else "white")
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


def page_images(raw_html: str) -> list[dict[str, Any]]:
    """Every image of a page's main content (`webpage`), with its file's address,
    its alt text and the headings above it."""
    _, found = webpage.read_page(raw_html, every_image=True)
    return [
        {
            "image_url": urljoin(config.SITE, element["image"]),
            "alt": element["text"],
            "section": element["section"],
        }
        for element in found
        if element["kind"] == "figure"
    ]


def figure_boxes(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A document reading's figures large enough to be pictures (MIN_SIDE points on
    each side), with their page, box, caption and section."""
    found = []
    for element in elements:
        box = element.get("bbox")
        if element["kind"] != "figure" or not box:
            continue
        left, top, right, bottom = box
        if right - left >= MIN_SIDE and bottom - top >= MIN_SIDE:
            found.append({
                "page": element["page"],
                "box": box,
                "alt": element["text"],
                "section": element["section"],
            })  # fmt: skip
    return found


def collect(
    pages: dict[str, str],
    readings: list[dict[str, Any]],
    stored: dict[str, Path],
    out: Path,
) -> list[dict[str, Any]]:
    """Every picture of the site's pages and documents stored once in `out` as PNG,
    and each place it is shown: the page or document (its URL), the page number of a
    document, its alt text or caption and its section. `pages` holds each page's HTML
    by URL; `stored` each collected file's path by URL."""
    out.mkdir(parents=True, exist_ok=True)
    places = []

    def keep(png: bytes, place: dict[str, Any]) -> None:
        identity = image_id(png)
        target = out / f"{identity}.png"
        if not target.exists():
            target.write_bytes(png)
        places.append(place | {"id": identity})

    for url, raw in pages.items():
        for image in page_images(raw):
            path = stored.get(image["image_url"])
            if path is None:
                continue  # not collected (a dead link)
            try:
                png = normalised(path.read_bytes())
            except UnidentifiedImageError:
                continue  # vector images (SVG) hold no pixels to read
            keep(png, image | {"source": url, "page": None})
    for reading in readings:
        url = reading["urls"][0]
        pdf = stored[url]
        for figure in figure_boxes(reading["elements"]):
            png = crop(pdf, figure["page"], tuple(figure["box"]))
            keep(png, {"source": url, "page": figure["page"], "alt": figure["alt"],
                       "section": figure["section"], "image_url": ""})  # fmt: skip
    return places


def new_words(text: str, known: str) -> float:
    """The share of a text's words not already in `known` (case folded)."""
    words = [word.casefold() for word in WORD.findall(text)]
    have = {word.casefold() for word in WORD.findall(known)}
    return sum(word not in have for word in words) / len(words) if words else 0.0


def read_text(picture: Image.Image, url: str) -> str:
    """The text GLM-OCR (the server at `url`) reads in a picture, or "" when its reply
    stopped at the token limit: a reply the model did not finish is a loop, not text
    (X43: eight plain colour swatches read as "1.1.1..." to 8,192 tokens). The request
    is `tables.recognise`'s, kept apart because `tables.py` is part of the PDF
    reader's fingerprint."""
    buffer = BytesIO()
    picture.save(buffer, format="PNG")
    address = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    content = [
        {"type": "image_url", "image_url": {"url": address}},
        {"type": "text", "text": OCR_PROMPT},
    ]
    body = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": OCR_MAX_TOKENS,
    }
    try:
        response = llm.CLIENT.post(
            f"{url}/v1/chat/completions",
            json=body,
            headers=llm.auth(),
            timeout=OCR_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        finished = choice["finish_reason"] == "stop"
        return str(choice["message"]["content"]) if finished else ""
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise llm.ModelServerError(f"vision model at {url} failed: {error}") from error


def ocr_lines(reading: str) -> list[str]:
    """The text a model read in a picture, as lines: inline LaTeX read as the
    characters it prints, markup tags dropped, empty lines and lines of markup alone
    left out. GLM-OCR answers a picture with no text by an empty code fence (X44 F1),
    and a swatch by a horizontal rule."""
    from limespec.tables import unlatex

    plain = TAG.sub(" ", unlatex(reading))
    lines = [" ".join(line.split()) for line in plain.splitlines()]
    return [line for line in lines if line and not MARKUP_LINE.fullmatch(line)]


def picture_passages(
    places: list[dict[str, Any]],
    read: dict[str, str],
    shown: dict[tuple[str, int | None], str],
    titles: dict[str, str],
) -> list[tuple[tuple[str, str, str, str, str, int | None], str]]:
    """One passage per picture: (url, title, heading, text, context, page) and its id.

    Shown in several places, a picture is filed under the place whose alt text says
    most about it (the first, on a tie). Its text is its own words: an alt text of
    DESCRIBED words or more, then the text read in it (`read`, by id) when at least
    NEW_WORDS of that is not already shown on its page (`shown`, by source and page).
    Its context, searched but never quoted, is lines: it is an image with its section
    path, then any shorter alt text. So a picture has words of its own exactly when
    its text is not empty or its context has more than one line (the picture
    channel's word ranking, `store`). Only places in a page or document of the build
    (`titles`) count (X44 F5).
    """
    chosen: dict[str, dict[str, Any]] = {}
    for place in [place for place in places if place["source"] in titles]:
        best = chosen.get(place["id"])
        if best is None or len(place["alt"]) > len(best["alt"]):
            chosen[place["id"]] = place
    found = []
    for identity, place in chosen.items():
        alt = " ".join(place["alt"].split())
        described = len(alt.split()) >= DESCRIBED
        lines = [alt] if described else []
        text = "\n".join(ocr_lines(read.get(identity, "")))
        known = shown.get((place["source"], place["page"]), "")
        if text and new_words(text, known) >= NEW_WORDS:
            lines.append(text)
        context = [" › ".join([PICTURE, *place["section"]])]
        if alt and not described:
            context.append(alt)
        url = place["source"]
        row = (url, titles[url], PICTURE, "\n".join(lines),
               "\n".join(context), place["page"])  # fmt: skip
        found.append((row, identity))
    return found

"""X43's image sets (evaluation/reports/X43-every-data-type.md, B2 and B3).

`image-text` is the OCR truth: images drawn in a fixed order, each looked at and its
printed text written down, until enough carry text. Candidates come from two sources,
each drawn round-robin across its groups so no group dominates: site images by their
folder (pack shots, gallery photos, layout images ...) and PDF figures by their
document's format (safety, technical, guide ...).
"""

import random
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from evaluation import webpages
from evaluation.lookups import TOP
from limespec import tables
from limespec.models import Passage

MIN_SIDE = 72  # points: a smaller PDF figure is a mark, not a picture (X43 B)
UNREADABLE = {"image/svg+xml"}  # vector images: no pixels to read
THUMB = 16  # pixels a side: thumbnails compared for copies
# Mean difference per colour value (of 255): copies measured 0.2-2.3, different
# pictures 8.7 or more (X43 B3).
COPY_DIFF = 5.0


def folder(url: str) -> str:
    """An image's folder on the site ("images/Products")."""
    return "/".join(urlsplit(url).path.strip("/").split("/")[:-1])


def interleaved[T](groups: Mapping[str, Sequence[T]], seed: int) -> list[T]:
    """Each group shuffled by the seed, then one from each group in turn."""
    rng = random.Random(seed)
    queues = []
    for name in sorted(groups):
        members = list(groups[name])
        rng.shuffle(members)
        queues.append(members)
    found: list[T] = []
    while any(queues):
        for queue in queues:
            if queue:
                found.append(queue.pop(0))
    return found


def site_candidates(
    records: Sequence[Mapping[str, Any]], seed: int
) -> list[dict[str, Any]]:
    """Collected site images, each file once, in drawing order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    seen = set()
    for record in records:
        if record["kind"] != "image" or record["content_type"] in UNREADABLE:
            continue
        if record["sha256"] in seen:
            continue
        seen.add(record["sha256"])
        groups.setdefault(folder(record["url"]), []).append({
            "id": f"site/{record['sha256'][:12]}",
            "sha256": record["sha256"],
            "url": record["url"],
            "group": folder(record["url"]),
        })  # fmt: skip
    return interleaved(groups, seed)


def figure_candidates(
    readings: Sequence[Mapping[str, Any]], formats: Mapping[str, str], seed: int
) -> list[dict[str, Any]]:
    """PDF figures at least MIN_SIDE points on each side, in drawing order, grouped
    by their document's format (`formats`: URL to catalogue format)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for reading in readings:
        url = reading["urls"][0]
        group = formats.get(url, "pdf:other")
        for number, element in enumerate(reading["elements"]):
            if element["kind"] != "figure" or not element["bbox"]:
                continue
            left, top, right, bottom = element["bbox"]
            if right - left < MIN_SIDE or bottom - top < MIN_SIDE:
                continue
            groups.setdefault(group, []).append({
                "id": f"figure/{reading['sha256'][:12]}/{number}",
                "sha256": reading["sha256"],
                "url": url,
                "page": element["page"],
                "box": element["bbox"],
                "group": group,
            })  # fmt: skip
    return interleaved(groups, seed)


def ocr_counts(truth: str, reading: str) -> dict[str, int]:
    """One image's word counts against its transcription, words compared as W2
    compares them (`webpages.tokens`): case and punctuation folded. The model's
    inline LaTeX is read as the characters it prints (`tables.unlatex`)."""
    wanted = Counter(webpages.tokens(truth))
    read = Counter(webpages.tokens(tables.unlatex(reading)))
    return {
        "words": sum(wanted.values()),
        "read": sum(read.values()),
        "right": sum((wanted & read).values()),
    }


def ocr_score(
    images: Sequence[Mapping[str, Any]], readings: Mapping[str, str]
) -> dict[str, Any]:
    """Recall and precision over the set and per source (site images, PDF figures),
    and each image's counts (X43 B2)."""
    rows = {}
    totals: dict[str, Counter[str]] = {"all": Counter()}
    for image in images:
        counts = ocr_counts(image["text"], readings[image["id"]])
        rows[image["id"]] = counts
        source = image["id"].split("/", 1)[0]
        for name in ("all", source):
            totals.setdefault(name, Counter()).update(counts)
    rates = {
        name: {
            "recall": total["right"] / total["words"],
            "precision": total["right"] / total["read"] if total["read"] else 0.0,
        }
        for name, total in totals.items()
    }
    return {"rates": rates, "images": rows}


def picture_draw(
    places: Sequence[Mapping[str, Any]], exclude: set[str], seed: int
) -> list[dict[str, Any]]:
    """Every stored picture not in `exclude`, once, in drawing order: site pictures
    by their folder and document figures by their document, each source in turn
    (X43 B3). Each comes with the first place it is shown."""
    first: dict[str, Mapping[str, Any]] = {}
    for place in places:
        if place["id"] not in exclude:
            first.setdefault(place["id"], place)
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {"site": {}, "figure": {}}
    for place in first.values():
        if place["page"] is None:
            source, group = "site", folder(place["image_url"])
        else:
            source, group = "figure", place["source"]
        groups[source].setdefault(group, []).append(dict(place))
    site = interleaved(groups["site"], seed)
    figures = interleaved(groups["figure"], seed)
    found: list[dict[str, Any]] = []
    for pair in zip(site, figures, strict=False):
        found += pair
    longer = site if len(site) > len(figures) else figures
    return found + longer[min(len(site), len(figures)) :]


def thumbnail(path: Path) -> bytes:
    """A picture shrunk to THUMB x THUMB colour pixels, for comparing pictures."""
    with Image.open(path) as picture:
        return picture.convert("RGB").resize((THUMB, THUMB)).tobytes()


def copies(ids: Sequence[str], folder: Path) -> dict[str, list[str]]:
    """Each picture with every stored picture that is a copy of it: thumbnails whose
    pixels differ by at most COPY_DIFF on average (one picture saved twice, or at
    another size). Different photographs of one product differ far more."""
    small = {identity: thumbnail(folder / f"{identity}.png") for identity in ids}

    def differ(one: bytes, other: bytes) -> float:
        return sum(abs(a - b) for a, b in zip(one, other, strict=True)) / len(one)

    return {
        identity: [
            other for other in ids if differ(small[identity], small[other]) <= COPY_DIFF
        ]
        for identity in ids
    }


def picture_result(
    item: Mapping[str, Any], ranked: Sequence[Passage]
) -> dict[str, Any]:
    """One image-facts question's result: the first rank among the top TOP
    passages of a passage made from an accepted picture."""
    rank = None
    for position, passage in enumerate(ranked[:TOP], 1):
        if passage.image and passage.image in item["accepted"]:
            rank = position
            break
    return {
        "id": item["id"],
        "set": item["set"],
        "cluster": item["cluster"],
        "kind": item["kind"],
        "success": 1.0 if rank else 0.0,
        "reciprocal": 1 / rank if rank else 0.0,
        "ceiling": 1.0,
    }

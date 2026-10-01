"""X44's multimodal retrieval set, `kb-probe`
(evaluation/reports/X44-pre-generation.md).

Sources are drawn by seed from the catalogue, a fixed number per stratum, and each
question is written from its source as a visitor sees it (`cases.source_text`: the
rendered page, the PDF's pypdf text, the Word file as LibreOffice lays it out, the
picture itself). Evidence is a list of nuggets: a span of at most NUGGET_WORDS words
stating the fact, or a picture by id. A question is found when what one search gives
holds every nugget: a text nugget in a passage, as the model reads it, of a document
that holds the span; a picture as a passage made from it or from a stored copy.
"""

import random
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from limespec.models import Passage, as_read
from limespec.verify import find_quote

SEED = 71
NUGGET_WORDS = 15
EXCERPT = 900  # characters of a source shown to the writer
# Strata in drawing order, with their number of questions (X44).
STRATA = {
    "web-content": 8,
    "listing": 6,
    "pdf-text": 8,
    "pdf-table": 6,
    "pdf-figure": 6,
    "picture-visual": 8,
    "picture-text": 6,
    "word": 6,
    "guidance": 6,
    "cross-type": 4,
}
PICTURE_STRATA = {"pdf-figure", "picture-visual", "picture-text"}
# Left out of the index by the user (X44 F5): general environment policy.
LEFT_OUT = "25-year-environment-plan.pdf"
Entry = dict[str, Any]
Item = dict[str, Any]


def strata(entry: Entry) -> list[str]:
    """The strata a catalogue entry can be drawn for (none for a source, or a
    picture shown, only in the document left out)."""
    kind = entry["format"]
    if entry["url"].endswith(LEFT_OUT):
        return []
    if kind == "page:colour":
        return ["listing"]
    if kind == "page:product":
        # /products and /products/<category> list cards; deeper pages are products.
        path = urlsplit(entry["url"]).path.strip("/").split("/")
        return (
            ["listing"] if path[0] == "products" and len(path) <= 2 else ["web-content"]
        )
    if kind.startswith("page:"):
        return ["web-content"]
    if kind.startswith("pdf:"):
        return ["pdf-text", "pdf-table"]
    if kind in ("image:visual", "image:text"):
        if entry.get("page"):
            return ["pdf-figure"]
        return ["picture-visual"] if kind == "image:visual" else ["picture-text"]
    if kind == "docx:declaration":
        return ["word"]
    if kind == "external:guidance":
        return ["guidance"]
    return []


def draw(entries: Sequence[Entry], seed: int = SEED) -> list[Item]:
    """The sources of every question, stratum by stratum. A stratum with fewer
    sources than questions (the guidance) draws a source again; a cross-type question
    pairs a PDF with a page that links it."""
    rng = random.Random(seed)
    found: list[Item] = []
    for stratum, count in STRATA.items():
        if stratum == "cross-type":
            linked = [
                e for e in entries if e["format"].startswith("pdf:") and e.get("pages")
            ]
            chosen = rng.sample(linked, count)
            pairs = [(entry, rng.choice(entry["pages"])) for entry in chosen]
        else:
            eligible = [e for e in entries if stratum in strata(e)]
            if len(eligible) >= count:
                chosen = rng.sample(eligible, count)
            else:
                chosen = [rng.choice(eligible) for _ in range(count)]
            pairs = [(entry, "") for entry in chosen]
        for entry, page in pairs:
            item = {"id": f"kb{len(found) + 1:02d}", "stratum": stratum,
                    "source": entry["id"]}  # fmt: skip
            if page:
                item["also"] = page
            found.append(item)
    return found


def nugget_problems(item: Item, own: str, pictures: set[str]) -> list[str]:
    """What is wrong with a written question: no question, no nugget, a text nugget
    too long or not in its own source's text (`own`), an unknown picture."""
    problems = []
    if not item.get("question", "").strip():
        problems.append(f"{item['id']}: no question")
    if not item.get("nuggets"):
        problems.append(f"{item['id']}: no nugget")
    for nugget in item.get("nuggets", []):
        if "picture" in nugget:
            if nugget["picture"] not in pictures:
                problems.append(f"{item['id']}: unknown picture {nugget['picture']}")
        elif len(nugget["text"].split()) > NUGGET_WORDS:
            problems.append(f"{item['id']}: a nugget over {NUGGET_WORDS} words")
        elif not find_quote(nugget["text"], own):
            problems.append(f"{item['id']}: not in its sources: {nugget['text']!r}")
    return problems


def sealed(
    item: Item,
    texts: Mapping[str, str],
    copies: Mapping[str, list[str]],
    own: Sequence[str],
) -> Item:
    """A written question as the set keeps it: each text nugget with every document
    (by URL) whose text holds it, each picture with its stored copies. A nugget
    marked `own` states a fact of the question's own sources (`own`, their URLs) in
    words other documents share ("Shelf life: 12 months", a product listed on a
    colour page), so only those sources hold it."""
    nuggets = []
    for nugget in item["nuggets"]:
        if "picture" in nugget:
            accepted = copies.get(nugget["picture"], [nugget["picture"]])
            nuggets.append({"picture": nugget["picture"], "accepted": accepted})
            continue
        places = own if nugget.get("own") else list(texts)
        holders = [url for url in places if find_quote(nugget["text"], texts[url])]
        nuggets.append({"text": nugget["text"], "holders": holders})
    return {"id": item["id"], "set": item["stratum"], "cluster": item["source"],
            "question": item["question"], "nuggets": nuggets}  # fmt: skip


def holds(passage: Passage, nugget: Mapping[str, Any]) -> bool:
    """Whether a passage holds a nugget, as the model reads it."""
    if "picture" in nugget:
        return bool(passage.image) and passage.image in nugget["accepted"]
    return passage.url in nugget["holders"] and bool(
        find_quote(nugget["text"], as_read(passage))
    )


def result(
    item: Item, given: Sequence[Passage], anywhere: Sequence[Passage]
) -> dict[str, Any]:
    """One question's result: found when the passages given hold every nugget; its
    reciprocal rank is that of the last nugget's first passage; the ceiling says
    whether the version (`anywhere`) holds every nugget at all."""
    ranks = []
    for nugget in item["nuggets"]:
        found = [n for n, passage in enumerate(given, 1) if holds(passage, nugget)]
        ranks.append(found[0] if found else 0)
    success = all(ranks)
    held = all(any(holds(p, nugget) for p in anywhere) for nugget in item["nuggets"])
    return {
        "id": item["id"],
        "set": item["set"],
        "cluster": item["cluster"],
        "success": 1.0 if success else 0.0,
        "reciprocal": 1 / max(ranks) if success else 0.0,
        "ceiling": 1.0 if held else 0.0,
    }


def pooled(results: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Success over the text strata, the picture strata and every question."""
    groups = {
        "text": [r for r in results if r["set"] not in PICTURE_STRATA],
        "pictures": [r for r in results if r["set"] in PICTURE_STRATA],
        "all": list(results),
    }
    return {
        name: sum(r["success"] for r in rows) / len(rows) if rows else 0.0
        for name, rows in groups.items()
    }

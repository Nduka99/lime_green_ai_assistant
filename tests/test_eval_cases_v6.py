"""Held-out v6's sources (X43): every data type, each seen as a visitor sees it.
Invented sources and keys."""

import json
import random
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from evaluation import cases, catalogue
from limespec import acquire, config

SITE = "https://www.lime-green.co.uk/"


def blank_pdf(path: Path, pages: int) -> None:
    # Pillow writes each page with a content stream, as every real PDF has.
    first, *rest = [Image.new("RGB", (200, 200), "white") for _ in range(pages)]
    first.save(path, format="PDF", save_all=True, append_images=rest)


def picture(tmp_path: Path, name: str = "p1") -> dict[str, Any]:
    Image.new("RGB", (10, 10), "green").save(tmp_path / f"{name}.png")
    return {
        "id": f"picture:{name}",
        "format": "image:visual",
        "topic": "lime-render",
        "source": str(tmp_path / f"{name}.png"),
        "url": SITE + "duro",
        "page": None,
        "alt": "",
        "read": "",
    }


def test_each_kind_of_source_offers_its_own_text(tmp_path: Path) -> None:
    page = {
        "id": "page:duro",
        "format": "page:product",
        "source": str(tmp_path / "duro.html"),
    }
    (tmp_path / "duro.txt").write_text("Duro as a browser shows it", encoding="utf-8")
    shown = picture(tmp_path) | {"page": 3, "alt": "Duro bag", "read": "Duro 25kg"}

    assert cases.source_text(page, tmp_path) == "Duro as a browser shows it"
    text = cases.source_text(shown)
    assert "Shown on: https://www.lime-green.co.uk/duro (page 3)" in text
    assert "Alt text: Duro bag" in text and text.endswith("Duro 25kg")
    assert "Alt text: (none)" in cases.picture_text(picture(tmp_path))


def test_a_word_file_offers_the_pdf_libreoffice_laid_it_out_as(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "READINGS", tmp_path)
    (tmp_path / "rendered").mkdir()
    blank_pdf(tmp_path / "rendered" / "abc.pdf", 1)
    entry = {"id": "file:abc", "format": "docx:declaration", "source": "x.docx"}

    assert cases.source_text(entry).startswith("[page 1]")


def test_v6_plans_visual_and_structure_cases_from_their_sources(tmp_path: Path) -> None:
    entries = [picture(tmp_path, f"p{n}") for n in range(3)]
    entries += [
        {"id": f"page:p{n}", "format": "page:knowledge", "topic": "faq",
         "source": f"p{n}.html", "url": SITE + f"p{n}"}
        for n in range(5)
    ]  # fmt: skip
    texts = {e["id"]: "Words to quote here. " * 20 for e in entries}
    design = {
        "prefix": "v6c",
        "counts": {"visual": 2, "structure": 2, "condition": 1, "out_of_domain": 1},
        "reuse": False,
        "styles": [["original"]],
        "unindexed": ["image"],
        "min_per_format": 2,
    }

    planned = cases.plan(entries, texts, 6, design)

    formats = {e["id"]: e["format"] for e in entries}
    kinds = {c["type"]: formats[c["sources"][0]] for c in planned if c["sources"]}
    assert kinds == {
        "visual": "image:visual",
        "structure": "page:knowledge",
        "condition": "page:knowledge",  # a condition is stated in words
    }
    assert (
        cases.usable_pool(entries, {e["id"]: "" for e in entries}, set()) == entries[:3]
    )


def test_a_picture_may_be_cited_as_what_it_shows_and_is_sealed_so(
    tmp_path: Path,
) -> None:
    shown = {"v6c01-s1": {"entry": "picture:p1", "text": "Alt text: (none)"}}
    plan = {"plan": [{"id": "v6c01", "type": "visual", "sources": ["picture:p1"],
                      "styles": ["original"]}], "sources": shown}  # fmt: skip
    case: dict[str, Any] = {
        "id": "v6c01", "type": "visual", "expected_status": "answered",
        "expected_answer": "A grey-green bag.", "must_not": [],
        "wordings": [{"style": "original", "text": "What colour is the bag?"}],
        "parts": [{"id": "A", "asks": "colour", "expected_answer": "grey-green",
                   "evidence": [{"source": "v6c01-s1", "visual": True}]}],
    }  # fmt: skip
    pictures = frozenset({"v6c01-s1"})

    assert cases.key_problems({"cases": [case]}, plan, set(), [], pictures) == []
    problems = cases.key_problems({"cases": [case]}, plan, set(), [])
    assert problems == [
        "v6c01 part 1 quote 1: only a picture can be cited as what it shows"
    ]
    case["wordings"][0]["text"] = "What colour is the bag in p1.png?"
    assert cases.key_problems({"cases": [case]}, plan, set(), [], pictures) == [
        "v6c01: a wording names a source id, marker, file or excerpt"
    ]
    case["wordings"][0]["text"] = "What colour is the bag?"

    entry = picture(tmp_path)
    assert cases.sealed_evidence({"visual": True}, entry)["kind"] == "image_visual"
    quoted = cases.sealed_evidence({"quote": "Duro"}, entry)
    assert (quoted["kind"], quoted["image"], quoted["quote"]) == (
        "image_text",
        "p1",
        "Duro",
    )
    docx = {"format": "docx:declaration", "url": SITE + "d.docx"}
    assert (
        cases.sealed_evidence({"quote": "A1", "page": 2}, docx)["kind"] == "docx_text"
    )


def test_an_earlier_key_took_its_quotes_from_the_page_not_its_pictures(
    tmp_path: Path,
) -> None:
    from evaluation import __main__ as cli

    page = {"id": "page:duro", "format": "page:product", "url": SITE + "duro"}
    entries = [page, picture(tmp_path)]  # the picture is shown on the same page
    shown = {"v5c01-s1": {"entry": "page:duro", "text": "t"}}
    (tmp_path / "plan.json").write_text(json.dumps({"plan": [], "sources": shown}))
    evidence = [{"url": SITE + "duro", "quote": "Duro is breathable."}]
    key = {"cases": [{"parts": [{"evidence": evidence}]}]}
    (tmp_path / "key.json").write_text(json.dumps(key))

    served, taken = cli.earlier_use([tmp_path], entries)

    assert served == frozenset({"page:duro"})
    assert taken == {"page:duro": ["Duro is breathable."]}


def test_the_bundle_shows_pictures_screenshots_and_document_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = tmp_path / "render"
    rendered.mkdir()
    Image.new("RGB", (10, 10), "white").save(rendered / "duro.png")
    blank_pdf(tmp_path / "sheet.pdf", 2)
    monkeypatch.setattr(config, "READINGS", tmp_path)
    (tmp_path / "rendered").mkdir()
    blank_pdf(tmp_path / "rendered" / "w.pdf", 1)
    out = tmp_path / "bundle"
    show = cases.asset_writer(out, rendered)

    assert show(picture(tmp_path), "v6c01-s1", "") == ["pictures/p1.png"]
    page = {"id": "page:duro", "format": "page:product", "source": "x/duro.html"}
    assert show(page, "v6c02-s1", "") == ["screenshots/duro.png"]
    assert show(page | {"source": "x/gone.html"}, "v6c02-s2", "") == []
    pdf = {
        "id": "file:s",
        "format": "pdf:technical",
        "source": str(tmp_path / "sheet.pdf"),
    }
    assert show(pdf, "v6c03-s1", "[page 2]\nText") == ["pages/v6c03-s1-p2.png"]
    word = {"id": "file:w", "format": "docx:declaration", "source": "w.docx"}
    assert show(word, "v6c04-s1", "[page 1]\nA1") == ["pages/v6c04-s1-p1.png"]
    assert (out / "pages" / "v6c04-s1-p1.png").exists()

    lines = cases.part_text(
        [{"id": "v6c01", "type": "visual", "sources": ["picture:p1"]}],
        {"picture:p1": picture(tmp_path)}, {"picture:p1": "Alt text: (none)"},
        8000, random.Random(1), {}, {}, show,
    )  # fmt: skip
    assert "See: pictures/p1.png" in lines


def test_the_catalogue_files_word_downloads_and_every_picture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = tmp_path / "site"
    pages.mkdir()
    (pages / "products__lime-render__duro.html").write_text(
        '<a href="/Documents/DoP.docx">DoP</a>', encoding="utf-8"
    )
    images = tmp_path / "images"
    images.mkdir()
    places = [
        {
            "id": "a",
            "source": SITE + "products/lime-render/duro",
            "page": None,
            "alt": "",
        },
        {"id": "a", "source": SITE + "other", "page": None, "alt": "Duro bag shown"},
        {
            "id": "b",
            "source": SITE + "products/lime-render/duro",
            "page": None,
            "alt": "",
        },
    ]
    (images / "places.json").write_text(json.dumps(places), encoding="utf-8")
    (images / "b.json").write_text(json.dumps({"ocr": "Duro lime render 25kg"}))
    records = [{"url": SITE + "Documents/DoP.docx", "kind": "document", "sha256": "d"}]
    monkeypatch.setattr(config, "PAGE_CACHE", pages)
    monkeypatch.setattr(config, "IMAGES", images)
    monkeypatch.setattr(acquire, "read_manifest", lambda: records)

    found = {e["id"]: e for e in catalogue.catalogue()}

    assert found["file:d"]["format"] == "docx:declaration"
    assert (found["picture:a"]["format"], found["picture:a"]["url"]) == (
        "image:visual", SITE + "other"
    )  # fmt: skip
    assert found["picture:b"]["format"] == "image:text"
    assert found["picture:b"]["topic"] == "lime-render"
    assert found["picture:a"]["pages"] == ["page:products__lime-render__duro"]
    monkeypatch.setattr(config, "IMAGES", tmp_path / "none")
    assert catalogue.pictures([]) == []


def test_a_flagged_picture_case_is_redrawn_from_the_plan_s_own_sources(
    tmp_path: Path,
) -> None:
    entries = [picture(tmp_path, f"p{n}") for n in range(3)]
    texts = {e["id"]: cases.picture_text(e) for e in entries}
    seen = {
        "plan": [{"id": "v6c01", "type": "visual", "sources": ["picture:p0"],
                  "styles": ["original"]},
                 {"id": "v6c02", "type": "visual", "sources": ["picture:p1"],
                  "styles": ["original"]}],
        "sources": {"v6c01-s1": {"entry": "picture:p0", "text": "t"},
                    "v6c02-s1": {"entry": "picture:p1", "text": "t"}},
        "reuse": True,
    }  # fmt: skip
    show = cases.asset_writer(tmp_path / "bundle", tmp_path)

    replaced, text = cases.rebundle(
        seen, {"v6c01"}, entries, texts, 8000, 1, {"image"}, show
    )

    assert replaced["plan"][0]["sources"] == ["picture:p2"]  # unused, not flagged
    assert "v6c01-s1" in replaced["sources"] and "v6c02-s1" in replaced["sources"]
    assert "See: pictures/p2.png" in text

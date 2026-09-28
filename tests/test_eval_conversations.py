"""Planning a conversation key and writing its bundle. Every source is invented."""

import json
import random
from pathlib import Path
from typing import Any

import pytest
from pypdf.errors import DependencyError, PdfReadError

from evaluation import __main__ as cli
from evaluation import conversations

PAGE = (
    "<html><body><main><h1>Duro Plaster</h1><p>Duro is a lime undercoat plaster.</p>"
    "<h2>Uses</h2><p>Brick and stone walls.</p></main></body></html>"
)
LONG_PAGE = PAGE.replace("stone walls.", "stone walls. " + "It breathes. " * 20)


class FakePage:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def extract_text(self) -> str | None:
        return self.text


class FakeReader:
    """Stands in for pypdf's PdfReader: two pages, one without a text layer."""

    def __init__(self, path: Path) -> None:
        if "locked" in str(path):
            raise DependencyError("cryptography>=3.1 is required for AES algorithm")
        if "broken" in str(path):
            raise PdfReadError("EOF marker not found")
        self.pages = [FakePage("Safety data sheet"), FakePage(None)]


def entry(entry_id: str, fmt: str, topic: str, **extra: Any) -> dict[str, Any]:
    return {"id": entry_id, "format": fmt, "topic": topic, "source": "", **extra}


def test_each_source_offers_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    monkeypatch.setattr(conversations, "PdfReader", FakeReader)

    text = conversations.source_text(entry("page:p", "page:product", "t", source=page))

    assert text == (
        "Duro Plaster\n\nDuro Plaster\nDuro is a lime undercoat plaster."
        "\n\nUses\nBrick and stone walls."
    )
    image = entry("file:i", "image", "t", text="Sponged finish of Motif")
    assert conversations.source_text(image) == "Sponged finish of Motif"
    pdf = entry("file:a", "pdf:safety", "t", source="sheet.pdf")
    assert conversations.source_text(pdf) == "Safety data sheet\n\n"
    for name in ["locked.pdf", "broken.pdf"]:
        assert (
            conversations.source_text(entry("file:b", "pdf:x", "t", source=name)) == ""
        )


def test_only_sources_with_something_to_quote_are_usable() -> None:
    assert conversations.usable(entry("i", "image", "t"), "Sponged finish of Motif")
    assert not conversations.usable(entry("i", "image", "t"), "Lime Green logo"[:9])
    assert conversations.usable(entry("p", "pdf:safety", "t"), "x" * 200)
    assert not conversations.usable(entry("p", "pdf:safety", "t"), " " * 300)


def test_the_plan_spreads_topics_and_mixes_formats() -> None:
    entries = [
        entry("a1", "page:product", "render"),
        entry("a2", "page:product", "render"),
        entry("a3", "pdf:safety", "render"),
        entry("a4", "image", "render"),
        entry("b1", "page:product", "mortar"),
        entry("b2", "pdf:technical", "mortar"),
        entry("u1", "page:news", "unknown"),  # no topic: never planned
        entry("x1", "pdf:guide", "mortar"),  # no usable text
    ]
    texts = {e["id"]: "x" * 300 for e in entries}
    texts["a4"] = "a rendered stone wall"
    texts["x1"] = ""

    planned = conversations.plan(entries, texts, conversations=3, turns=3, seed=1)

    assert [c["id"] for c in planned] == ["c01", "c02", "c03"]
    assert sorted({c["topic"] for c in planned}) == ["mortar", "render"]
    sources = [s for c in planned for s in c["sources"]]
    assert len(sources) == len(set(sources))  # no source is used twice
    assert "u1" not in sources and "x1" not in sources
    by_id = {e["id"]: e for e in entries}
    first = next(c for c in planned if c["topic"] == "render")
    formats = [by_id[s]["format"] for s in first["sources"]]
    assert len(set(formats)) == 3  # three formats before any repeats
    assert planned[0]["dynamics"] == conversations.DYNAMICS[:2]
    assert planned[1]["dynamics"] == conversations.DYNAMICS[2:4]
    third = planned[2]  # the topic's sources ran out: fewer than 3
    assert len(third["sources"]) < 3


def test_a_long_text_is_cut_to_a_window_starting_at_a_paragraph() -> None:
    text = "intro\n\n" + "one\n\n" * 50 + "end"

    short, start = conversations.excerpt("short", 100, random.Random(1))
    window, where = conversations.excerpt(text, 30, random.Random(1))

    assert (short, start) == ("short", 0)
    assert len(window) == 30 and window == text[where : where + 30]
    assert where == 0 or text[where - 2 : where] == "\n\n"


def test_the_bundle_writes_parts_images_and_what_the_writer_saw(
    tmp_path: Path,
) -> None:
    image = tmp_path / "stored-image"
    image.write_bytes(b"jpeg bytes")
    entries = [
        entry("page:p", "page:product", "render", url="https://x.test/duro"),
        entry("file:i", "image", "render", url="https://x.test/i/wall.jpg?v=9",
              source=str(image)),
        entry("file:g", "pdf:guide", "render", url="https://x.test/guide.pdf"),
    ]  # fmt: skip
    texts = {"page:p": "Duro plaster", "file:i": "A wall", "file:g": "a\n\nb" * 40}
    planned = [
        {"id": "c01", "topic": "render", "sources": ["page:p", "file:i"],
         "dynamics": ["d1", "d2"]},
        {"id": "c02", "topic": "render", "sources": ["file:g"], "dynamics": ["d3"]},
    ]  # fmt: skip
    out = tmp_path / "bundle"

    parts = conversations.bundle(
        planned, entries, texts, "the brief", out, per_part=1, limit=50, seed=3
    )

    assert [p.name for p in parts] == ["part-1.md", "part-2.md"]
    assert (out / "brief.md").read_text() == "the brief"
    assert (out / "c01-s2.jpg").read_bytes() == b"jpeg bytes"
    first = parts[0].read_text()
    assert "# Conversation c01: render" in first and "Include: d1; d2." in first
    assert "Image file: c01-s2.jpg. Alt text (quote only this):" in first
    assert "Excerpt from character" in parts[1].read_text()
    seen = json.loads((out / "plan.json").read_text())
    assert seen["plan"] == planned
    assert seen["sources"]["c01-s1"] == {"entry": "page:p", "text": "Duro plaster"}
    assert len(seen["sources"]["c02-s1"]["text"]) == 50


def test_nothing_usable_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="nothing to plan"):
        conversations.plan([entry("p", "page:news", "news")], {"p": ""}, 1, 1, seed=1)


def test_the_command_line_plans_and_writes_the_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "page.html"
    page.write_text(LONG_PAGE, encoding="utf-8")
    listed = tmp_path / "catalogue.json"
    source = entry("page:p", "page:product", "render", source=str(page))
    listed.write_text(json.dumps([{**source, "url": "https://x.test/p"}]))
    brief = tmp_path / "brief.md"
    brief.write_text("the brief")
    out = tmp_path / "bundle"

    code = cli.main(["plan-conversations", "--catalogue", str(listed),
                     "--brief", str(brief), "--out", str(out), "--seed", "1",
                     "--conversations", "1", "--turns", "1"])  # fmt: skip

    assert code == 0
    printed = capsys.readouterr().out
    assert "    1  page:product" in printed
    assert printed.endswith(f"1 conversations, 1 sources, 1 parts in {out}\n")

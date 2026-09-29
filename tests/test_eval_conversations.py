"""Planning a conversation key and writing its bundle. Every source is invented."""

import json
import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pypdf.errors import DependencyError, PdfReadError

from evaluation import __main__ as cli
from evaluation import catalogue, conversations, sets
from limespec import assistant, store

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
    image = entry("i", "image", "t")
    assert conversations.usable(image, "Sponged finish of Motif plaster")
    assert not conversations.usable(image, "Cannock mill 1")  # shorter than a quote
    assert conversations.usable(entry("p", "pdf:safety", "t"), "x" * 200)
    assert not conversations.usable(entry("p", "pdf:safety", "t"), " " * 300)


def test_each_conversation_follows_one_subject() -> None:
    duro = ["page:duro"]
    entries = [
        entry("page:duro", "page:product", "render"),
        entry("file:sds", "pdf:safety", "render", pages=duro),
        entry("file:sds2", "pdf:safety", "render", pages=duro),
        entry("file:tds", "pdf:technical", "render", pages=duro),
        entry("page:solo", "page:product", "render"),
        entry("file:dop", "pdf:performance", "render", pages=["page:solo"]),
        entry("page:ashlar", "page:product", "mortar"),
        entry("file:adl1", "external:guidance", "regulation", pages=[]),
        entry("page:news", "page:news", "unknown"),  # no topic: never planned
        entry("file:guide", "pdf:guide", "render", pages=duro),  # no usable text
    ]
    texts = {e["id"]: "x" * 300 for e in entries}
    texts["file:guide"] = ""

    planned = conversations.plan(entries, texts, conversations=5, turns=3, seed=1)

    # Four subjects: Duro with its files, Solo with its file, Ashlar, and ADL1,
    # which no page links. The topic change takes Solo, the smallest subject left,
    # so planning stops after three conversations.
    assert [(c["topic"], c["sources"], c["shift"]) for c in planned] == [
        ("regulation", ["file:adl1"], ""),
        ("render", ["page:duro", "file:sds", "file:tds", "page:solo"], "page:solo"),
        ("mortar", ["page:ashlar"], ""),
    ]
    assert planned[1]["dynamics"] == conversations.DYNAMICS[2:4]
    assert conversations.TOPIC_CHANGE in planned[1]["dynamics"]


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
         "shift": "file:i", "dynamics": ["d1", "d2"]},
        {"id": "c02", "topic": "render", "sources": ["file:g"], "shift": "",
         "dynamics": ["d3"]},
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
    assert "## Source c01-s2 (image), another subject, for the topic change" in first
    assert "Excerpt from character" in parts[1].read_text()
    seen = json.loads((out / "plan.json").read_text())
    assert seen["plan"] == planned
    assert seen["sources"]["c01-s1"] == {"entry": "page:p", "text": "Duro plaster"}
    assert len(seen["sources"]["c02-s1"]["text"]) == 50


def test_nothing_usable_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="nothing to plan"):
        conversations.plan([entry("p", "page:news", "news")], {"p": ""}, 1, 1, seed=1)


SEEN = {
    "plan": [
        {"id": "c01", "topic": "plaster", "sources": ["page:p", "file:i"],
         "dynamics": ["pronoun follow-up (it)", "emergency arising mid-conversation"]},
    ],
    "sources": {
        "c01-s1": {"entry": "page:p",
                   "text": "Duro is a lime undercoat plaster\nfor brick and stone."},
        "c01-s2": {"entry": "file:i", "text": "Sponged finish of Motif plaster"},
    },
}  # fmt: skip


def turn(number: int, **changes: Any) -> dict[str, Any]:
    """A sound turn of conversation c01, with any fields changed."""
    duro = {"source": "c01-s1", "quote": "lime undercoat plaster for brick"}
    written = {
        "id": f"c01t{number}",
        "message": "where can duro go",
        "standalone_question": "Where can Duro plaster be used?",
        "dynamic": "first question" if number == 1 else "plain follow-up",
        "standalone": number == 1,
        "expected_status": "answered",
        "expected_answer": "On brick and stone.",
        "parts": [{"id": "p1", "asks": "where", "expected_answer": "Brick and stone.",
                   "evidence": [duro]}],
        "must_not": ["Duro is a finish coat."],
    }  # fmt: skip
    return {**written, **changes}


def sound_key() -> dict[str, Any]:
    motif = {"source": "c01-s2", "quote": "Sponged finish of Motif plaster"}
    finish = {"id": "p1", "asks": "finish", "expected_answer": "Sponged.",
              "evidence": [motif]}  # fmt: skip
    turns = [
        turn(1),
        turn(2, dynamic="pronoun follow-up", message="and its finish?", parts=[finish]),
        turn(3, dynamic="emergency arising mid-conversation (it went in my eye)",
             expected_status="safety_referral", expected_answer="", parts=[]),
    ]  # fmt: skip
    return {"conversations": [{"id": "c01", "turns": turns}]}


def test_a_sound_key_has_no_problems() -> None:
    assert conversations.key_problems(sound_key(), SEEN) == []


def test_each_turn_follows_the_brief() -> None:
    key = sound_key()
    duro = key["conversations"][0]["turns"][0]["parts"][0]
    duro["evidence"] = [
        {"source": "c01-s1", "quote": "Duro is"},
        {"source": "c01-s1", "quote": "Duro is a lime render plaster"},
        {"source": "c02-s1", "quote": "Duro is a lime undercoat plaster"},
    ]
    key["conversations"][0]["turns"] = [
        key["conversations"][0]["turns"][0],
        turn(2, id="c01t9", dynamic="topic change", message="and c01-s2?"),
        turn(3, dynamic="first question", standalone=False),
        turn(4, dynamic="emergency arising mid-conversation", parts=[{"id": "p1"}]),
        turn(5, expected_status="safety_referral"),
        turn(6, expected_status="unknown", parts=[]),
        turn(7, dynamic="ellipsis follow-up", standalone=True, parts=[]),
        turn(8, message=None),
    ]

    assert conversations.key_problems(key, SEEN) == [
        "c01: 8 turns, not 3 to 5",
        "c01t1 p1 quote 1 (c01-s1) has 2 words",
        "c01t1 p1 quote 2 (c01-s1) is not in the source as shown",
        "c01t1 p1 quote 3: c02-s1 is not its source",
        "c01t2: id is c01t9",
        "c01t2: dynamic 'topic change' is not one of its situations",
        "c01t2: message names a source id or alt text",
        "c01t3: dynamic 'first question' is not one of its situations",
        "c01t3: the first question must be standalone",
        "c01t4: emergency arising mid-conversation must be safety_referral",
        "c01t4 p1: no asks",
        "c01t4 p1: no expected_answer",
        "c01t4 p1: no evidence",
        "c01t5: safety_referral must have no parts",
        "c01t5: safety_referral leaves expected_answer empty",
        "c01t6: unknown expected_status 'unknown'",
        "c01t7: dynamic 'ellipsis follow-up' is not one of its situations",
        "c01t7: ellipsis follow-up cannot be standalone",
        "c01t7: answered but has no parts",
        "c01t8: message is missing or not a str",
        "c01: c01-s2 is never quoted",
        "c01: no turn is a pronoun follow-up",
    ]


def test_every_planned_conversation_is_written_once() -> None:
    key = sound_key()
    first = key["conversations"][0]
    key["conversations"] = [first, first, {"id": "c09", "turns": []}]
    assert conversations.key_problems(key, SEEN) == [
        "conversation ids are not unique",
        "c09: not planned",
    ]
    assert conversations.key_problems({"conversations": []}, SEEN) == [
        "c01: not written"
    ]


def test_the_command_line_checks_a_key_split_into_parts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "plan.json"
    seen.write_text(json.dumps(SEEN))
    first = tmp_path / "key-part-1.json"
    first.write_text(json.dumps(sound_key()))
    second = tmp_path / "key-part-2.json"
    second.write_text(json.dumps({"conversations": [{"id": "c02", "turns": []}]}))

    assert cli.main(["check-conversations", str(first), "--plan", str(seen)]) == 0
    leaning = "2 of 2 later turns lean on earlier turns\n"
    assert capsys.readouterr().out == "1 conversations, 3 turns, 0 problems\n" + leaning
    code = cli.main(
        ["check-conversations", str(first), str(second), "--plan", str(seen)]
    )
    assert code == 1
    assert capsys.readouterr().out == (
        "PROBLEM c02: not planned\n2 conversations, 3 turns, 1 problems\n" + leaning
    )


def test_only_a_clean_key_is_written_and_never_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = tmp_path / "plan.json"
    seen.write_text(json.dumps(SEEN))
    part = tmp_path / "key-part-1.json"
    part.write_text(json.dumps({"conversations": []}))
    key = tmp_path / "set" / "key.json"
    command = ["check-conversations", str(part), "--plan", str(seen), "--out", str(key)]

    assert cli.main(command) == 1  # c01 is not written, so nothing is sealed
    assert not key.exists()
    part.write_text(json.dumps(sound_key()))
    assert cli.main(command) == 0
    assert json.loads(key.read_text(encoding="utf-8")) == sound_key()
    assert cli.main(command) == 1
    assert capsys.readouterr().out.endswith(f"key not written: {key} exists\n")


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


COVERED_KEY: dict[str, Any] = {"conversations": [{"id": "c01", "turns": [
    {"id": "c01t1", "standalone": True, "expected_status": "answered", "parts": []},
    {"id": "c01t2", "standalone": False, "expected_status": "answered", "parts": [
        {"evidence": [{"source": "c01-s1", "quote": "Add  4 LITRES"},
                      {"source": "c01-s2", "quote": "never indexed"}]},
        {"evidence": [{"source": "c01-s1", "quote": "Mix for 3 minutes."}]}]},
    {"id": "c01t3", "standalone": False, "expected_status": "answered", "parts": [
        {"evidence": [{"source": "c01-s3", "quote": "An image's alt text"}]}]},
    {"id": "c01t4", "standalone": False, "expected_status": "safety_referral",
     "parts": []},
]}]}  # fmt: skip
TEXTS = ["Mixing\nAdd 4 litres of water.", "Mix for 3 minutes. Then apply."]


def test_a_follow_up_is_in_scope_when_every_part_has_a_quote_in_one_passage() -> None:
    texts = [conversations.squashed(text) for text in TEXTS]
    turns = COVERED_KEY["conversations"][0]["turns"]

    assert conversations.in_scope(turns[1], texts)
    assert not conversations.in_scope(turns[2], texts)
    assert conversations.in_scope(turns[3], texts)  # a referral always is
    assert conversations.coverage(COVERED_KEY, TEXTS) == {
        "follow_ups": 2,
        "covered": 1,
        "missing": ["c01t3"],
    }


def test_coverage_is_counted_for_an_index_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "conv"
    folder.mkdir()
    plan = {"plan": [], "sources": {"c01-s1": {"entry": "page:a"},
                                    "c01-s2": {"entry": "file:b"},
                                    "c01-s3": {"entry": "file:c"}}}  # fmt: skip
    (folder / "key.json").write_text(json.dumps(COVERED_KEY), encoding="utf-8")
    (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    sets.register("conv", "invented", tmp_path, tmp_path / "sets.json")

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "searchable_texts", lambda conn, version: TEXTS)
    monkeypatch.setattr(
        catalogue, "catalogue", lambda: [{"id": "file:c", "format": "image"}]
    )
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]

    assert cli.main([*base, "coverage", "conv", "--version", "11"]) == 0
    output = capsys.readouterr().out
    assert "1 of 2 answerable follow-ups in scope in version 11" in output
    assert "1  quotes of uncovered turns from image" in output

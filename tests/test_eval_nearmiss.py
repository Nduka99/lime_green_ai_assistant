"""E7 S3: the in-domain near-miss set. Invented passages and replies; the model
servers are stand-ins."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import graders, nearmiss
from limespec import assistant, lists, llm, store
from limespec.models import Passage

TEXT = "Solo dries in 2 days. Protect it from frost while it cures. " * 4
SOLO = Passage(7, "https://example.test/products/solo", "Solo", "Drying", TEXT, "d")
SDS = Passage(8, "https://example.test/solo-sds.pdf", "Solo — SDS", "4", TEXT, "d")
SHEET = Passage(9, "https://example.test/solo.pdf", "Solo — Data", "", TEXT, "d")
GUIDE = Passage(10, "https://example.test/guide", "Guide", "Frost", TEXT, "d")
LIST = Passage(11, "https://example.test/products/x", "X", lists.HEADING, TEXT, "d")
SHORT = Passage(12, "https://example.test/guide", "Guide", "Note", "Short.", "d")


def written_reply(near_quote: str = "Protect it from frost") -> dict[str, Any]:
    return {
        "answerable": [
            {"question": "How long does Solo take to dry?",
             "quote": "Solo dries in 2 days."},
            {"question": "Is Solo made of cheese?", "quote": "not in the passage"},
        ],
        "near_miss": [
            {"question": "What is Solo's frost resistance rating?",
             "quote": near_quote},
            {"question": "How long does Solo stay workable?",
             "quote": "dries in 2 days"},
        ],
    }  # fmt: skip


def test_passages_are_drawn_evenly_by_kind_without_lists_or_short_ones() -> None:
    assert nearmiss.kind_of(SOLO) == "product page"
    assert nearmiss.kind_of(SDS) == "safety data sheet"
    assert nearmiss.kind_of(SHEET) == "data sheet"
    assert nearmiss.kind_of(GUIDE) == "guide or article"

    taken = nearmiss.sample([SOLO, SDS, SHEET, GUIDE, LIST, SHORT], 4, seed=1)

    assert {p.id for p in taken} == {7, 8, 9, 10}
    assert len(nearmiss.sample([SOLO, GUIDE], 9, seed=1)) == 2


def test_questions_become_claim_items_and_unfound_quotes_are_dropped() -> None:
    seen: list[str] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        seen.append(user)
        return written_reply()

    found = nearmiss.written(SOLO, chat)

    assert [(i["id"], i["label"]) for i in found] == [
        ("p7/a1", "correct"),
        ("p7/n1", "off_question"),
        ("p7/n2", "off_question"),
    ]
    assert found[0]["sources"] == [["Solo", "Drying", "Solo dries in 2 days."]]
    assert found[0]["case"] == "p7" and found[0]["kind"] == "product page"
    assert seen[0].startswith("Document: Solo › Drying\nPassage:\n")
    with pytest.raises(llm.ModelServerError, match="does not match"):
        nearmiss.written(SOLO, lambda s, u, schema: [])


def reply_with(content: object) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def test_only_questions_the_second_model_agrees_with_are_kept() -> None:
    found = nearmiss.written(SOLO, lambda s, u, schema: written_reply())

    def send(body: dict[str, Any]) -> dict[str, Any]:
        question = body["messages"][1]["content"].rsplit("Question: ", 1)[1]
        said = "dry" in question or "workable" in question
        return reply_with({"answer": "yes" if said else "no"})

    kept = nearmiss.checked(found, {"p7": SOLO}, send)

    # The checker says the passage answers the second near-miss question: dropped.
    assert [i["id"] for i in kept] == ["p7/a1", "p7/n1"]


def test_claims_shown_from_the_passage_alone_are_counted() -> None:
    found = nearmiss.written(SOLO, lambda s, u, schema: written_reply())
    quote = {"source_id": "S1", "quote": "Solo dries in 2 days."}
    claim = {"part": 1, "text": "Solo dries in 2 days.", "evidence": [quote]}

    shown = nearmiss.shown_claims(
        found[:1], {"p7": SOLO}, lambda body: reply_with({"claims": [claim]})
    )

    assert shown == {"p7/a1": 1}


def test_the_command_line_writes_checks_and_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "searchable_passages", lambda conn, v: [SOLO])
    monkeypatch.setattr(store, "load_passages", lambda conn, ids: [SOLO])
    monkeypatch.setattr(llm, "chat", lambda s, u, schema: written_reply())

    def send(body: dict[str, Any]) -> dict[str, Any]:
        checking = body["messages"][0]["content"] == nearmiss.CHECK_PROMPT
        return reply_with({"answer": "yes"} if checking else {"claims": []})

    monkeypatch.setattr(graders, "post_to", lambda url: send)
    items, kept, shown = (
        tmp_path / n for n in ("items.json", "kept.json", "shown.json")
    )
    version = ["--version", "17"]

    assert cli.main(["nearmiss-write", *version, "--count", "1", "--seed", "71",
                     "--out", str(items)]) == 0  # fmt: skip
    assert cli.main(["nearmiss-check", str(items), *version, "--url", "http://g",
                     "--out", str(kept)]) == 0  # fmt: skip
    assert cli.main(["nearmiss-answer", str(items), *version, "--url", "http://q",
                     "--out", str(shown)]) == 0  # fmt: skip

    out = capsys.readouterr().out
    assert "3 questions from 1 passages" in out and "1 of 3 questions kept" in out
    assert json.loads(shown.read_text()) == {"p7/a1": 0, "p7/n1": 0, "p7/n2": 0}

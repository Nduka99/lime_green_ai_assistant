"""Replaying the first request and the searches without generating answers (E5).
Every key, question and passage here is invented."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import replay, sets
from limespec import answer, assistant, store
from limespec.models import Passage

KEY: dict[str, Any] = {"cases": [
    {"id": "k1", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "What is in Duro?"},
                  {"style": "rushed", "text": "duro in my eye"}],
     "parts": [{"id": "p1",
                "evidence": [{"kind": "page_text", "quote": "free of cement"}]}]},
    {"id": "k2", "expected_status": "insufficient_evidence",
     "wordings": [{"style": "original", "text": "What does Duro cost?"}],
     "parts": []},
]}  # fmt: skip
QUESTIONS = [
    {"id": "q1", "question": "What is in Duro?"},
    {"id": "q2", "question": "duro in my eye"},
    {"id": "q3", "question": "What does Duro cost?"},
]
DURO = Passage(
    1, "https://example.test/duro", "Duro", "", "Duro is free of cement.", ""
)
SOLO = Passage(2, "https://example.test/solo", "Solo", "", "Solo is for interiors.", "")


def understand(question: str) -> tuple[bool, list[str]]:
    return "eye" in question, ["what is in Duro", "is Duro a plaster"]


def retrieve(query: str) -> list[Passage]:
    return [DURO] if "what is in" in query else [SOLO]


def test_each_answerable_question_is_searched_as_the_assistant_would() -> None:
    written, given = replay.replay(KEY, QUESTIONS, understand, retrieve)

    assert written == {"q1": ["what is in Duro", "is Duro a plaster"], "q2": []}
    # Two parts: searched together, then each alone, interleaved without repeats.
    assert given == {"q1": [DURO, SOLO], "q2": []}


def test_search_questions_from_an_earlier_replay_are_kept() -> None:
    def never(question: str) -> tuple[bool, list[str]]:
        raise AssertionError("the first request must not run again")

    kept = {"q1": ["is Duro a plaster"], "q2": []}

    written, given = replay.replay(KEY, QUESTIONS, never, retrieve, kept)

    assert written == kept
    assert given == {"q1": [SOLO], "q2": []}


def test_the_command_line_replays_and_scores_reach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "keyed"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (folder / "questions.json").write_text(json.dumps({"questions": QUESTIONS}))
    sets.register("keyed", "invented", tmp_path, tmp_path / "sets.json")
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(assistant, "retriever", lambda conn, version: retrieve)
    monkeypatch.setattr(answer, "understand", lambda q, chat: understand(q))
    monkeypatch.setattr(store, "searchable_texts", lambda conn, v: [DURO.text])
    monkeypatch.setattr(store, "picture_passages", lambda conn, version: {})
    out = tmp_path / "replay.json"
    command = [*base, "replay", "keyed", "--version", "12", "--out", str(out)]

    assert cli.main(command) == 0
    assert capsys.readouterr().out == (
        "parts reached 1/2 (0.500); in the version 2/2 (1.000); "
        "questions with every part reached 1/2\n"
    )
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["passages"] == {"q1": [1, 2], "q2": []}
    assert saved["parts"]["q2"] == []
    monkeypatch.setattr(answer, "understand", lambda q, chat: 1 / 0)
    again = tmp_path / "again.json"
    assert cli.main([*command[:-1], str(again), "--parts", str(out)]) == 0
    assert json.loads(again.read_text(encoding="utf-8"))["rows"] == saved["rows"]

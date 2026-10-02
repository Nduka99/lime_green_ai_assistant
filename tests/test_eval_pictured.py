"""The first request's picture marks measured on a set (E10). Invented questions."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import pictured, sets
from limespec import answer, llm
from limespec.models import Part

QUESTIONS = [
    {"id": "q1", "question": "What colour is the Duro bag?"},
    {"id": "q2", "question": "How long does Duro take to set?"},
]


def test_a_question_counts_as_marked_when_any_of_its_parts_is() -> None:
    def understand(question: str) -> list[Part]:
        return [Part("Duro?"), Part(question, pictured="colour" in question)]

    found = pictured.read(QUESTIONS, understand)

    assert found["questions"] == 2 and found["marked"] == ["q1"]
    assert found["parts"]["q1"][1] == {
        "question": "What colour is the Duro bag?",
        "pictured": True,
    }


def test_the_command_line_runs_the_answer_path_s_first_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "questions.json").write_text(json.dumps({"questions": QUESTIONS}))
    sets.register("demo", "invented", tmp_path, tmp_path / "sets.json")
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]
    seen: list[str] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        seen.append(system)
        asked = {"question": user, "items": [],
                 "asks_what_a_picture_shows": "colour" in user}  # fmt: skip
        return {"describes_exposure": False, "search_questions": [asked]}

    monkeypatch.setattr(llm, "chat", chat)
    out = tmp_path / "marks.json"

    assert cli.main([*base, "picture-parts", "demo", "--out", str(out)]) == 0

    assert set(seen) == {answer.UNDERSTAND_PROMPT}
    assert "demo: 1 of 2 questions have a part marked" in capsys.readouterr().out
    assert json.loads(out.read_text())["demo"]["marked"] == ["q1"]

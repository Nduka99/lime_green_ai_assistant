"""E8 G0: the smoke test of a candidate generator. Invented passages; the model server
is a stand-in."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import candidates, graders, sets
from limespec import answer, assistant, store
from limespec.models import Passage

SOLO = Passage(
    7, "https://example.test/solo", "Solo", "Drying", "Solo dries in 2 days.", "d"
)
ITEMS = [
    {"id": f"p7/a{n}", "case": "p7", "parts": ["How long does Solo dry?"]}
    for n in range(5)
]
UNDERSTOOD = {
    "describes_exposure": False,
    "search_questions": [
        {
            "question": "Solo drying time",
            "items": [],
            "asks_what_a_picture_shows": False,
        }
    ],
}
QUOTE = {"source_id": "S1", "quote": "Solo dries in 2 days."}
CLAIM = {"part": 1, "text": "Solo dries in 2 days.", "evidence": [QUOTE]}


def reply(content: object, finish: str = "stop") -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content)
    return {"choices": [{"finish_reason": finish, "message": {"content": text}}]}


def model(varying: bool = False, broken: bool = False) -> candidates.Send:
    calls = []

    def send(body: dict[str, Any]) -> dict[str, Any]:
        calls.append(body)
        if body["messages"][0]["content"] == answer.UNDERSTAND_PROMPT:
            return reply("not json" if broken else UNDERSTOOD)
        claim = (
            CLAIM | {"text": f"Solo dries in 2 days ({len(calls)})."}
            if varying
            else CLAIM
        )
        return reply({"claims": [claim]})

    return send


def test_a_candidate_doing_both_requests_repeatably_passes() -> None:
    result = candidates.smoke(["q"] * 5, ITEMS, {"p7": SOLO}, model())

    assert result == {"first_request": 5, "answers": 5, "repeated": 5, "passes": True}


def test_broken_json_or_changing_replies_fail() -> None:
    broken = candidates.smoke(["q"] * 5, ITEMS, {"p7": SOLO}, model(broken=True))
    varying = candidates.smoke(["q"] * 5, ITEMS, {"p7": SOLO}, model(varying=True))
    cut = candidates.smoke(
        ["q"], ITEMS[:1], {"p7": SOLO}, lambda b: reply("{", "length")
    )

    assert broken["first_request"] == 0 and not broken["passes"]
    assert varying["repeated"] == 0 and not varying["passes"]
    assert cut == {"first_request": 0, "answers": 0, "repeated": 0, "passes": False}


def test_the_command_line_writes_the_smoke_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "demo"
    folder.mkdir()
    questions = [
        {"id": f"q{n}", "question": "How long does Solo dry?"} for n in range(5)
    ]
    (folder / "questions.json").write_text(json.dumps({"questions": questions}))
    sets.register("demo", "invented", tmp_path, tmp_path / "sets.json")
    items = tmp_path / "items.json"
    items.write_text(json.dumps(ITEMS))

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "load_passages", lambda conn, ids: [SOLO])
    monkeypatch.setattr(graders, "post_to", lambda url: model())
    out = tmp_path / "smoke.json"
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]

    command = ["smoke", "--url", "http://c", "--set", "demo", "--items", str(items)]
    assert cli.main([*base, *command, "--version", "17", "--out", str(out)]) == 0

    assert json.loads(out.read_text())["passes"] is True
    assert '"passes": true' in capsys.readouterr().out

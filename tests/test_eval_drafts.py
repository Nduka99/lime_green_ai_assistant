"""Drafting answers again to judge a change to verification (E5). Every question,
passage and claim here is invented."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import drafts
from limespec import assistant, llm, store
from limespec.answer import UNDERSTAND_SCHEMA
from limespec.models import Passage

DURO = Passage(
    1, "https://example.test/duro", "Duro", "", "Duro is free of cement.", ""
)
CLAIMS = [
    {"part": 1, "text": "Duro is free of cement.",
     "evidence": [{"source_id": "S1", "quote": "Duro is free of cement."}]},
    {"part": 1, "text": "Duro sets in 3 days.",
     "evidence": [{"source_id": "S1", "quote": "Duro is free of cement."}]},
]  # fmt: skip


def chat(system: str, user: str, schema: dict[str, Any]) -> object:
    if schema is UNDERSTAND_SCHEMA:
        exposed = "eye" in user
        asked = [
            {
                "question": "what is in Duro",
                "items": [],
                "asks_what_a_picture_shows": False,
            }
        ]
        return {"describes_exposure": exposed, "search_questions": asked}
    return {"claims": CLAIMS}


def test_every_draft_is_kept_with_the_verdict_of_the_checks() -> None:
    found = drafts.drafted("What is in Duro?", [DURO], chat)

    assert found["parts"] == ["what is in Duro"]
    kept, dropped = found["drafts"]
    assert kept["removed"] == "" and kept["evidence"] == CLAIMS[0]["evidence"]
    assert dropped["removed"] == "number not in its quotes: 3"
    assert drafts.removed([{"id": "a7", **found}]) == ["a7/2"]


def test_an_emergency_or_an_empty_search_drafts_nothing() -> None:
    nothing: dict[str, Any] = {"parts": [], "drafts": []}

    assert drafts.drafted("Duro in my eye", [DURO], chat) == nothing
    assert drafts.drafted("What is in Duro?", [], chat) == nothing


def test_labelled_drafts_are_checked_again_as_the_checks_stand() -> None:
    item = {"id": "a7", "passages": [1], **drafts.drafted("Duro?", [DURO], chat)}
    # As if an earlier rule had removed the first draft too, wrongly.
    labels = {"a7/1": "wrong", "a7/2": "right"}

    found = drafts.rescore([item], labels, {1: DURO})

    assert found["wrong"] == {"of": 1, "kept": ["a7/1"]}
    assert found["right"] == {"of": 1, "kept": []}
    assert drafts.rescore([item], {}, {1: DURO})["wrong"]["of"] == 0


def test_the_command_line_drafts_again_then_scores_the_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "answers-candidate.json"
    view = {"question": "What is in Duro?"}
    records = [
        {"id": "q1", "answer_id": 7, "view": view},
        {"id": "q2", "http": None, "error": "refused"},  # no audit record
        {"id": "q3", "answer_id": 8, "view": view},  # nothing was removed
        {"id": "q4", "answer_id": 9, "view": view},  # the same request as q1
    ]
    run.write_text(json.dumps(records), encoding="utf-8")

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    dropped = {7: [{"text": "x", "reason": "no quote"}], 8: [], 9: [{"text": "y"}]}
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "removed_claims", lambda conn, i: dropped[i])
    monkeypatch.setattr(store, "given_passages", lambda conn, i: (12, [DURO]))
    monkeypatch.setattr(store, "load_passages", lambda conn, ids: [DURO])
    monkeypatch.setattr(llm, "chat", chat)
    items = tmp_path / "items.json"

    assert cli.main(["drafts", str(run), "--out", str(items)]) == 0
    assert "1 answers drafted again, 1 drafts removed" in capsys.readouterr().out
    saved = json.loads(items.read_text(encoding="utf-8"))
    assert saved[0]["id"] == "a7" and saved[0]["passages"] == [1]
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"a7/2": {"label": "right", "why": "3 is invented"}}))
    assert cli.main(["verify-score", str(items), str(labels)]) == 0
    assert json.loads(capsys.readouterr().out)["right"] == {"of": 1, "kept": []}
    labels.write_text(json.dumps({"a7/1": {"label": "wrong"}}))
    assert cli.main(["verify-score", str(items), str(labels)]) == 1
    assert "label every removed draft" in capsys.readouterr().err

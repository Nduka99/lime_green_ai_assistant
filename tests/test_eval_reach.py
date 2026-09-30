import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import reach, sets
from limespec import assistant, store
from limespec.models import Passage

KEY: dict[str, Any] = {"cases": [
    {"id": "k1", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "What is in Duro?"},
                  {"style": "rushed", "text": "duro ingredients"}],
     "parts": [
         {"id": "p1", "evidence": [{"kind": "page_text", "quote": "free of cement"}]},
         {"id": "p2", "evidence": [{"kind": "pdf_text", "quote": "3 to 6 mm"},
                                   {"kind": "image_alt", "quote": "a photo"}]},
         {"id": "p3", "evidence": [{"kind": "image_alt", "quote": "only a photo"}]}]},
    {"id": "k2", "expected_status": "insufficient_evidence",
     "wordings": [{"style": "original", "text": "What does Duro cost?"}],
     "parts": []},
]}  # fmt: skip
QUESTIONS = [
    {"id": "q1", "question": "What is in Duro?"},
    {"id": "q2", "question": "duro ingredients"},
    {"id": "q3", "question": "What does Duro cost?"},
]


def passage(passage_id: int, text: str) -> Passage:
    return Passage(passage_id, "https://example.test/duro", "Duro", "", text, "")


def test_only_text_evidence_counts_and_parts_keep_their_ids() -> None:
    parts = reach.part_quotes(KEY["cases"][0])

    assert parts == [("p1", ["free of cement"]), ("p2", ["3 to 6 mm"])]
    assert reach.part_quotes({"parts": [{"evidence": [{"quote": "x y"}]}]}) == [
        ("p1", ["x y"])
    ]


def test_a_part_is_reached_when_every_quote_is_in_a_given_passage() -> None:
    given = {
        "q1": [
            passage(1, "Duro is free  of cement."),
            passage(2, "Joints of 3 to 6 mm."),
        ],
        "q2": [passage(1, "Duro is free of cement.")],
    }
    versions = ["Duro is free of cement.", "Joints of 3 to 6 mm."]

    rows = reach.score(KEY, QUESTIONS, given, versions)

    assert [(r["id"], r["part"], r["reached"], r["ceiling"]) for r in rows] == [
        ("q1", "p1", True, True),
        ("q1", "p2", True, True),
        ("q2", "p1", True, True),
        ("q2", "p2", False, True),
    ]
    assert reach.summary(rows) == {
        "parts": 4, "reached": 3, "ceiling": 4, "questions": 2, "every_part": 1,
    }  # fmt: skip


def test_a_quote_cannot_match_across_two_passages_of_the_version() -> None:
    rows = reach.score(KEY, QUESTIONS[:1], {}, ["Duro is free of", "cement. 3 to 6 mm"])

    assert [row["ceiling"] for row in rows] == [False, True]


def test_the_summary_reads_as_one_line_even_for_an_empty_key() -> None:
    found = reach.summary([])

    assert reach.text(found) == (
        "parts reached 0/0 (0.000); in the version 0/0 (0.000); "
        "questions with every part reached 0/0"
    )


def write_set(tmp_path: Path) -> list[str]:
    folder = tmp_path / "keyed"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (folder / "questions.json").write_text(
        json.dumps({"questions": QUESTIONS}), encoding="utf-8"
    )
    sets.register("keyed", "invented", tmp_path, tmp_path / "sets.json")
    return ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]


def test_reach_reads_each_answer_s_given_passages_from_its_audit_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_set(tmp_path)
    run = tmp_path / "answers-candidate.json"
    records = [
        {"id": "q1", "answer_id": 7},
        {"id": "q2", "http": None, "error": "refused"},  # no audit record
        {"id": "q3", "answer_id": 8},
    ]
    run.write_text(json.dumps(records), encoding="utf-8")
    given = {7: [passage(1, "Duro is free of cement. Joints of 3 to 6 mm.")], 8: []}

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "given_passages", lambda conn, i: (11, given[i]))
    monkeypatch.setattr(
        store, "searchable_texts", lambda conn, version: ["Duro is free of cement."]
    )
    out = tmp_path / "reach.json"

    assert cli.main([*base, "reach", "keyed", str(run), "--out", str(out)]) == 0
    assert capsys.readouterr().out == (
        "parts reached 2/4 (0.500); in the version 2/4 (0.500); "
        "questions with every part reached 1/2\n"
    )
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["summary"]["every_part"] == 1
    assert len(saved["rows"]) == 4


def test_a_run_spanning_index_versions_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_set(tmp_path)
    run = tmp_path / "answers-mixed.json"
    run.write_text(
        json.dumps([{"id": "q1", "answer_id": 1}, {"id": "q3", "answer_id": 2}])
    )

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "given_passages", lambda conn, i: (i, []))

    assert cli.main([*base, "reach", "keyed", str(run)]) == 1
    assert "one index version, not [1, 2]" in capsys.readouterr().err


def test_removed_claims_are_listed_by_reason_beside_what_was_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "answers-c3.json"
    shown = {"claims": [{"text": "Duro is free of cement."}]}
    records = [
        {"id": "q1", "question": "Duro?", "answer_id": 7, "view": shown},
        {"id": "q2", "http": None, "error": "refused"},  # no audit record
    ]
    run.write_text(json.dumps(records), encoding="utf-8")
    removed = [
        {"text": "Duro is grey.", "reason": "does not answer the question"},
        {"text": "Duro costs £5.", "reason": "states a price"},
    ]

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "removed_claims", lambda conn, i: removed)
    out = tmp_path / "removed.json"

    arguments = ["removed", str(run), "--out", str(out),
                 "--reason", "does not answer the question"]  # fmt: skip
    assert cli.main(arguments) == 0

    assert "1 removed claims" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8")) == [
        {"id": "q1", "question": "Duro?", "removed": "Duro is grey.",
         "reason": "does not answer the question",
         "kept": ["Duro is free of cement."]}
    ]  # fmt: skip
    assert cli.main(["removed", str(run), "--out", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 2

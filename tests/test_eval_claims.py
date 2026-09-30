"""The claim benchmark for the sufficiency gate (E5). Every key, answer, label and
score here is invented."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import claims, sets

KEY: dict[str, Any] = {"cases": [
    {"id": "k1", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "What is in Duro?"},
                  {"style": "rushed", "text": "duro ingredients"}]},
    {"id": "k2", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "Is Solo for interiors?"}]},
]}  # fmt: skip
QUESTIONS = [
    {"id": "q1", "question": "What is in Duro?"},
    {"id": "q2", "question": "duro ingredients"},
    {"id": "q3", "question": "Is Solo for interiors?"},
]


def view(*texts: str) -> dict[str, Any]:
    return {
        "status": "answered",
        "claims": [{"text": text, "sources": [1]} for text in texts],
        "sources": [{"number": 1, "quote": "a quote"}],
    }


PAIRS = [
    {"id": "q1", "question": "What is in Duro?", "A": view("No cement.", "Sets fast."),
     "B": view("No cement.")},
    {"id": "q2", "question": "duro ingredients",
     "A": {"status": "insufficient_evidence", "claims": []}},
    {"id": "q3", "question": "Is Solo for interiors?", "A": view("Yes, interiors.")},
]  # fmt: skip
LABELS = {
    "q1/A": ["correct", "off_question"],
    "q1/B": ["correct"],
    "q3/A": ["correct"],
}


def test_each_distinct_claim_is_one_item_with_its_parts_quotes_and_label() -> None:
    found = claims.items(
        "demo", KEY, QUESTIONS, PAIRS, LABELS, {"q1": ["what is in Duro"]}
    )

    assert [item["id"] for item in found] == ["demo/q1/A1", "demo/q1/A2", "demo/q3/A1"]
    assert found[0] == {
        "id": "demo/q1/A1",
        "case": "demo/k1",
        "question": "What is in Duro?",
        "parts": ["what is in Duro"],
        "claim": "No cement.",
        "quotes": ["a quote"],
        "label": "correct",
    }
    assert found[2]["parts"] == ["Is Solo for interiors?"]  # no replay: the question


def test_the_threshold_withholds_at_most_the_allowed_share_of_correct_claims() -> None:
    scores = [float(n) for n in range(1, 30)]  # 29 correct claims

    # (k + 1) / 30 <= 0.1 allows k = 2 below the threshold.
    assert claims.threshold(scores) == 3.0
    assert claims.threshold(scores[:8]) == float("-inf")  # too few to calibrate on
    assert claims.threshold([]) == float("-inf")


def many(count: int, label: str, case: str) -> list[dict[str, Any]]:
    return [{"id": f"{case}-{label}-{n}", "case": case, "label": label}
            for n in range(count)]  # fmt: skip


def test_a_detector_is_scored_on_the_half_it_was_not_calibrated_on() -> None:
    found = []
    for case in ("c1", "c2", "c3", "c4"):
        found += many(20, "correct", case) + many(2, "off_question", case)
    scores = {item["id"]: 1.0 if item["label"] == "correct" else 0.0 for item in found}

    result = claims.score(found, scores, seed=1)

    assert result["auc"] == 1.0 and result["threshold"] == 1.0
    assert result["correct_withheld"] == {"count": 0, "of": 40, "share": 0.0}
    assert result["not_correct_caught"] == {"count": 4, "of": 4, "share": 1.0}
    assert result["caught_by_label"] == {"off_question": {"count": 4, "of": 4}}
    assert result["qualifies"] is True
    flat = dict.fromkeys(scores, 0.5)
    assert claims.score(found, flat, seed=1)["qualifies"] is False
    alone = many(1, "correct", "c1")
    assert claims.score(alone, {alone[0]["id"]: 1.0}, seed=1)["qualifies"] is False


def test_the_command_line_builds_the_items_and_scores_a_detector(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "demo"
    sitting = folder / "sitting"
    sitting.mkdir(parents=True)
    (folder / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (folder / "questions.json").write_text(json.dumps({"questions": QUESTIONS}))
    (sitting / "pairs.json").write_text(json.dumps(PAIRS), encoding="utf-8")
    (sitting / "claims.json").write_text(json.dumps(LABELS), encoding="utf-8")
    replayed = tmp_path / "replay.json"
    replayed.write_text(json.dumps({"parts": {"q1": ["what is in Duro"]}}))
    sets.register("demo", "invented", tmp_path, tmp_path / "sets.json")
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]
    out = tmp_path / "items.json"

    assert cli.main([*base, "claim-items", "--set", "demo", str(sitting), str(replayed),
                     "--out", str(out)]) == 0  # fmt: skip
    assert "3 claims" in capsys.readouterr().out
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({"demo/q1/A1": 0.9, "demo/q1/A2": 0.1}))
    assert cli.main(["claim-score", str(out), str(scores), "--seed", "1"]) == 1
    assert "1 items have no score, e.g. demo/q3/A1" in capsys.readouterr().err
    scores.write_text(json.dumps({"demo/q1/A1": 0.9, "demo/q1/A2": 0.1,
                                  "demo/q3/A1": 0.8}))  # fmt: skip
    assert cli.main(["claim-score", str(out), str(scores), "--seed", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["auc"] == 1.0

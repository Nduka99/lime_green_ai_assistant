"""Comparing two runs question by question: which answers differ, the blind pairs,
and the unblinded differences. Every set and answer here is invented."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import keys, pairs


def case(case_id: str, kind: str, status: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "type": kind,
        "expected_status": status,
        "wordings": [
            {"style": "original", "text": f"{case_id} original?"},
            {"style": "rushed", "text": f"{case_id} rushed?"},
        ],
    }


KEY = {
    "cases": [
        case("joints", "single_fact", "answered"),
        case("swallowed", "exposure_emergency", "safety_referral"),
    ]
}
QUESTIONS = keys.blind_questions(KEY, seed=7, prefix="t")


def record(row: dict[str, str], status: str, text: str = "") -> dict[str, Any]:
    view = {"question": row["question"], "status": status, "claims": [text]}
    return {"id": row["id"], "question": row["question"], "view": view}


def by_id(records: list[dict[str, Any]]) -> pairs.Records:
    return {r["id"]: r for r in records}


def runs() -> dict[str, pairs.Records]:
    """v5 answers everything as expected; pg changes one joints answer and refers
    only one of the two emergencies."""
    v5, pg = [], []
    for row in QUESTIONS:
        emergency = row["question"].startswith("swallowed")
        status = "safety_referral" if emergency else "answered"
        v5.append(record(row, status, "3 to 6 mm"))
        pg.append(record(row, status, "3 to 6 mm"))
    joints = next(r for r in pg if r["question"] == "joints rushed?")
    joints["view"]["claims"] = ["3 to 60 mm"]
    swallowed = next(r for r in pg if r["question"] == "swallowed rushed?")
    swallowed["view"]["status"] = "answered"
    return {"v5": by_id(v5), "pg": by_id(pg)}


def question_id(text: str) -> str:
    return next(row["id"] for row in QUESTIONS if row["question"] == text)


def test_only_answers_that_differ_are_compared() -> None:
    first, second = runs().values()
    error = {"id": "x", "question": "q", "error": "503"}

    found = pairs.differing(first, second, [row["id"] for row in QUESTIONS])

    assert sorted(found) == sorted(
        [question_id("joints rushed?"), question_id("swallowed rushed?")]
    )
    assert pairs.differing({"x": error}, {"x": dict(error)}, ["x"]) == []
    assert pairs.shown(error) == {"error": "503"}


def test_blind_pairs_hide_the_runs_and_unblind_restores_them() -> None:
    ids = [row["id"] for row in QUESTIONS]

    blinded, order = pairs.blind(ids, runs(), seed=28)
    again, _ = pairs.blind(ids, runs(), seed=28)

    assert blinded == again  # the same seed shuffles the same way
    assert all(sorted(names) == ["pg", "v5"] for names in order.values())
    assert "v5" not in json.dumps(blinded) and "pg" not in json.dumps(blinded)
    verdicts = {
        pair["id"]: {"A": {"verdict": "sound"}, "B": {"verdict": "wrong"}}
        for pair in blinded
    }
    graded = pairs.unblind(verdicts, order)
    for qid, names in order.items():
        assert graded[qid][names[0]] == {"verdict": "sound"}
        assert graded[qid][names[1]] == {"verdict": "wrong"}


def test_differences_are_counted_per_case_with_status_and_referrals() -> None:
    graded = {
        question_id("joints rushed?"): {
            "v5": {"verdict": "sound"},
            "pg": {"verdict": "wrong"},
        },
        question_id("swallowed rushed?"): {
            "v5": {"verdict": "sound"},
            "pg": {"verdict": "wrong"},
        },
    }

    result = pairs.compare(KEY, QUESTIONS, runs(), graded)

    assert result["status_matched"] == {"v5": 4, "pg": 3}
    assert result["referred"] == {"v5": 2, "pg": 1}
    assert result["sound"]["difference"] == -2
    assert result["wrong"]["difference"] == 2
    assert result["sound"]["low"] <= -2 <= result["sound"]["high"]
    table = pairs.markdown(result)
    assert "| Status as the key expects | 4/4 | 3/4 |" in table
    assert "| Safety referral on emergency questions | 2/2 | 1/2 |" in table
    assert "Answers that differ: 2 of 4" in table
    assert "| sound | -2 |" in table


def make_set(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Path]:
    folder = root / "demo"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(KEY))
    (folder / "questions.json").write_text(json.dumps({"questions": QUESTIONS}))
    first, second = root / "answers-v5.json", root / "answers-pg.json"
    for path, name in [(first, "v5"), (second, "pg")]:
        path.write_text(json.dumps(list(runs()[name].values())))
    assert run(capsys, root, "register", "demo")[0] == 0
    return first, second


def run(capsys: pytest.CaptureFixture[str], root: Path, *argv: str) -> tuple[int, str]:
    code = cli.main(["--root", str(root), "--registry", str(root / "sets.json"), *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_the_command_line_writes_blind_pairs_then_compares_their_verdicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = make_set(tmp_path, capsys)
    out = tmp_path / "blind"
    files = [str(first), str(second)]

    code, text = run(capsys, tmp_path, "blind", "demo", *files, "--seed", "28",
                     "--out", str(out))  # fmt: skip
    assert (code, text) == (0, f"2 of 4 answers differ; pairs in {out}\n")
    blinded = json.loads((out / "pairs.json").read_text())
    code, text = run(capsys, tmp_path, "unblind", "demo", *files, "--dir", str(out))
    assert code == 1 and "verdicts.json" in text  # nothing graded yet

    verdicts = {
        pair["id"]: {"A": {"verdict": "sound"}, "B": {"verdict": "sound"}}
        for pair in blinded
    }
    one = dict(list(verdicts.items())[:1])
    (out / "verdicts.json").write_text(json.dumps(one))
    code, text = run(capsys, tmp_path, "unblind", "demo", *files, "--dir", str(out))
    assert code == 1 and "every pair" in text
    (out / "verdicts.json").write_text(json.dumps(verdicts))
    code, text = run(capsys, tmp_path, "unblind", "demo", *files, "--dir", str(out))
    assert code == 0 and "| sound | +0 |" in text
    code, text = run(capsys, tmp_path, "unblind", "demo", *files, "--dir", str(out),
                     "--json")  # fmt: skip
    assert json.loads(text)["differing"] == 2


def test_two_runs_with_the_same_file_name_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, _ = make_set(tmp_path, capsys)

    code, text = run(capsys, tmp_path, "blind", "demo", str(first), str(first),
                     "--seed", "1", "--out", str(tmp_path / "x"))  # fmt: skip

    assert code == 1 and "different file names" in text

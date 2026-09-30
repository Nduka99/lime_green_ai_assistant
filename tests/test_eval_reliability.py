"""Answer reliability (R0): risk, coverage, refusals, second graders and their
agreement. Every key, answer and verdict here is invented."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import graders, metrics, reliability, sets
from limespec import llm

KEY: dict[str, Any] = {
    "cases": [
        {"id": "c1", "type": "simple", "expected_status": "answered",
         "expected_answer": "3 to 6 mm.",
         "parts": [{"asks": "Joint size", "expected_answer": "3 to 6 mm."}],
         "must_not": [],
         "wordings": [{"style": "original", "text": "Mortex joints?"},
                      {"style": "rushed", "text": "mortex joint size"}]},
        {"id": "c2", "type": "absent", "expected_status": "insufficient_evidence",
         "must_not": [{"rule": "A price is given."}],
         "wordings": [{"style": "original", "text": "Mortex heat capacity?"}]},
        {"id": "c3", "type": "emergency", "expected_status": ["safety_referral"],
         "questions": [{"style": "original", "text": "Mortex in my eye"}]},
    ]
}  # fmt: skip
QUESTIONS = [
    {"id": "q1", "question": "Mortex joints?"},
    {"id": "q2", "question": "mortex joint size"},
    {"id": "q3", "question": "Mortex heat capacity?"},
    {"id": "q4", "question": "Mortex in my eye"},
]


def record(qid: str, status: str, claims: list[str] | None = None) -> dict[str, Any]:
    view = {"status": status, "notice": "",
            "claims": [{"text": t, "sources": [1]} for t in claims or []]}  # fmt: skip
    return {"id": qid, "question": qid, "view": view, "seconds": 1.0}


RUNS = {
    "live": {"q1": record("q1", "answered", ["3 to 6 mm."]),
             "q2": record("q2", "answered", ["3 to 6 mm."]),
             "q3": record("q3", "insufficient_evidence"),
             "q4": record("q4", "safety_referral")},
    "cand": {"q1": record("q1", "answered", ["10 mm."]),
             "q2": record("q2", "answered", ["3 to 6 mm."]),
             "q3": record("q3", "answered", ["It is 900 J/kgK."]),
             "q4": record("q4", "safety_referral")},
}  # fmt: skip


def graded(live: list[str], cand: list[str]) -> dict[str, dict[str, Any]]:
    return {
        qid: {"live": {"verdict": a}, "cand": {"verdict": b}}
        for qid, a, b in zip(("q1", "q2", "q3", "q4"), live, cand, strict=True)
    }


GRADED = graded(
    ["sound", "sound", "sound", "sound"], ["wrong", "sound", "wrong", "sound"]
)


def test_wilson_bounds_hold_at_zero_and_in_the_middle() -> None:
    assert metrics.wilson(0, 0) == (0.0, 1.0)
    low, high = metrics.wilson(0, 73)
    assert low == 0.0 and high == pytest.approx(0.05, abs=0.001)
    low, high = metrics.wilson(5, 10)
    assert low == pytest.approx(1 - high)


def test_kappa_corrects_agreement_for_chance() -> None:
    assert metrics.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "b", "b"]) == 0.5
    assert metrics.cohen_kappa(["a", "a"], ["a", "a"]) == 1.0


def test_cases_are_the_unit_of_risk_coverage_and_refusals() -> None:
    rows = reliability.case_rows(KEY, QUESTIONS, GRADED, RUNS)
    arms = reliability.by_arm(rows)

    live, cand = arms["live"]["all"], arms["cand"]["all"]
    assert live["risk"]["count"] == 0 and live["risk"]["of"] == 1
    assert live["coverage"]["share"] == 1.0 and live["refusals"]["share"] == 1.0
    assert live["emergencies"]["share"] == 1.0 and live["consistency"]["share"] == 1.0
    # c1 has one wrong wording and c2 answered what should be refused: two wrong cases.
    assert cand["risk"]["count"] == 2 and cand["risk"]["of"] == 2
    assert cand["wrong_cases"] == ["c1", "c2"]
    assert cand["coverage"]["share"] == 0.0 and cand["refusals"]["share"] == 0.0
    assert cand["consistency"]["share"] == 0.0
    assert set(arms["cand"]["types"]) == {"absent", "emergency", "simple"}


def test_coverage_is_compared_case_by_case() -> None:
    rows = reliability.case_rows(KEY, QUESTIONS, GRADED, RUNS)

    found = reliability.coverage_difference(rows, "cand", "live")

    assert found["difference"] == -1.0


def test_shortfalls_are_attributed_to_retrieval_or_generation() -> None:
    rows = reliability.case_rows(
        KEY,
        QUESTIONS,
        graded(["partial"] * 4, ["missing", "wrong", "sound", "sound"]),
        RUNS,
    )
    reached = reliability.reached_parts(
        [{"id": "q1", "reached": False}, {"id": "q2", "reached": True}]
    )

    found = reliability.attribution(rows, {"cand": reached})

    assert found["cand"] == {"missing by retrieval": 1, "wrong by generation": 1}
    assert found["live"] == {"partial by generation": 2}


def test_claim_precision_counts_correct_claims() -> None:
    found = reliability.claim_precision(
        {"q1": ["correct", "off_question"], "q2": ["correct"]}
    )

    assert found["labels"] == {"correct": 2, "off_question": 1}
    assert found["precision"]["count"] == 2 and found["precision"]["of"] == 3


def test_claim_labels_by_item_are_read_per_arm_through_the_order() -> None:
    order = {"q1": [["cand"], ["live", "old"]]}

    found = reliability.claims_by_arm(
        {"q1/A": ["incorrect"], "q1/B": ["correct"]}, order
    )

    assert found == {"cand": {"q1": ["incorrect"]}, "live": {"q1": ["correct"]},
                     "old": {"q1": ["correct"]}}  # fmt: skip


def blinded() -> list[dict[str, Any]]:
    return [
        {"id": "q1", "question": "Mortex joints?", "A": RUNS["cand"]["q1"]["view"],
         "B": RUNS["live"]["q1"]["view"]},
        {"id": "q3", "question": "Mortex heat capacity?", "A": {"error": "boom"}},
    ]  # fmt: skip


def test_items_carry_the_key_and_the_answer_but_no_run() -> None:
    found = graders.items(KEY, QUESTIONS, blinded())

    assert [i["item"] for i in found] == ["q1/A", "q1/B", "q3/A"]
    assert found[0]["key"]["parts"] == [
        {"asks": "Joint size", "expected_answer": "3 to 6 mm."}
    ]
    assert found[0]["answer"] == {
        "status": "answered",
        "notice": "",
        "claims": ["10 mm."],
    }
    assert found[2]["answer"]["status"] == "error"
    assert found[2]["key"]["must_not"] == [{"rule": "A price is given."}]
    prompt = json.loads(graders.grader_prompt(found[0]))
    assert set(prompt) == {"question", "key", "answer"}


def test_frozen90_parts_give_their_answer_to_the_grader() -> None:
    case = {"expected_status": ["answered"], "parts": [{"asks": "x?", "answer": "y."}]}

    assert graders.key_view(case)["parts"] == [{"asks": "x?", "expected_answer": "y."}]


def test_a_sample_keeps_every_wrong_or_missing_item_and_a_share_per_type() -> None:
    found = graders.items(KEY, QUESTIONS, blinded())

    chosen = graders.sample(found, {"q1/B": "wrong"}, share=0.5, seed=1)

    # q1/B (graded wrong), q3/A (its type's only item) and half of simple's two.
    assert [i["item"] for i in chosen] == ["q1/A", "q1/B", "q3/A"]


def test_verdicts_are_flattened_by_item_from_either_shape() -> None:
    nested = {"q1": {"A": {"verdict": "sound"}, "B": {"verdict": "wrong"}}}
    assert graders.flat(nested) == {"q1/A": "sound", "q1/B": "wrong"}
    assert graders.flat({"q1/A": {"verdict": "partial", "reason": "r"}}) == {
        "q1/A": "partial"}  # fmt: skip


def test_a_model_grades_each_item_through_a_chat_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append({"url": url, **kwargs["json"]})
        content = json.dumps({"verdict": "wrong", "reason": "10 mm is not the key's."})
        body = {"choices": [{"message": {"content": content}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.CLIENT, "post", post)
    found = graders.items(KEY, QUESTIONS, blinded())[:1]

    verdicts = graders.grade(found, "GUIDE", graders.post_to("http://127.0.0.1:8083/"))

    assert verdicts == {
        "q1/A": {"verdict": "wrong", "reason": "10 mm is not the key's."}
    }
    assert sent[0]["url"] == "http://127.0.0.1:8083/v1/chat/completions"
    assert sent[0]["messages"][0]["content"] == "GUIDE"


def test_agreement_is_kappa_over_the_items_both_graded() -> None:
    found = graders.agreement(
        {"a": "sound", "b": "wrong", "c": "sound"},
        {"a": "sound", "b": "sound", "d": "x"},
    )

    assert found["items"] == 2 and found["agreed"] == 1
    assert found["table"] == {"sound / sound": 1, "wrong / sound": 1}
    assert graders.agreement({}, {})["kappa"] == 0.0


def test_the_majority_of_three_settles_the_items_all_three_graded() -> None:
    primary = {"q1": {"A": {"verdict": "sound", "reason": "r"},
                      "B": {"verdict": "wrong", "reason": "r"}},
               "q2": {"A": {"verdict": "partial", "reason": "r"}},
               "q3": {"A": {"verdict": "sound", "reason": "r"}}}  # fmt: skip
    second = {"q1/A": "sound", "q1/B": "partial", "q2/A": "wrong"}
    third = {"q1/A": "wrong", "q1/B": "partial", "q2/A": "sound"}

    final, unsettled = graders.settle(primary, [second, third], {})

    assert final["q1"]["A"] == primary["q1"]["A"]  # the primary is in the majority
    assert final["q1"]["B"]["verdict"] == "partial"
    assert final["q3"] == primary["q3"]  # not in the second graders' sample
    assert unsettled == ["q2/A"]
    written = {"q2/A": {"verdict": "partial", "reason": "read: one part right"}}
    final, unsettled = graders.settle(primary, [second, third], written)
    assert final["q2"]["A"] == written["q2/A"] and unsettled == []
    assert graders.majority(["sound", "wrong"]) is None


# The command line.


def write_set(tmp_path: Path) -> list[str]:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (folder / "questions.json").write_text(json.dumps({"questions": QUESTIONS}))
    sets.register("demo", "invented", tmp_path, tmp_path / "sets.json")
    return ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]


def test_the_command_line_blinds_every_question_then_reads_reliability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_set(tmp_path)
    runs = []
    for name, records in RUNS.items():
        path = tmp_path / f"answers-{name}.json"
        path.write_text(json.dumps(list(records.values())), encoding="utf-8")
        runs.append(str(path))
    sitting = tmp_path / "sitting"
    sitting.mkdir()

    assert cli.main([*base, "blind", "demo", *runs, "--seed", "3", "--all",
                     "--out", str(sitting)]) == 0  # fmt: skip
    assert "4 of 4 questions (every question)" in capsys.readouterr().out
    pairs_written = json.loads((sitting / "pairs.json").read_text(encoding="utf-8"))
    assert len(pairs_written) == 4  # q4's one shared answer is graded too
    verdicts = {p["id"]: {s: {"verdict": "sound", "reason": "r"}
                          for s in "ABCDEFGH" if s in p}
                for p in pairs_written}  # fmt: skip
    (sitting / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    reach = tmp_path / "reach-cand.json"
    reach.write_text(json.dumps({"rows": [{"id": "q1", "reached": True}]}))
    out = tmp_path / "reliability.json"

    assert cli.main([*base, "reliability", "demo", *runs, "--dir", str(sitting),
                     "--reach", str(reach), "--baseline", "live",
                     "--out", str(out)]) == 0  # fmt: skip
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["arms"]["cand"]["all"]["risk"]["of"] == 2
    assert saved["coverage_difference"]["cand"]["difference"] == 0.0
    capsys.readouterr()

    bundle = tmp_path / "bundle"
    arguments = [*base, "grading-bundle", "demo", "--dir", str(sitting),
                 "--out", str(bundle), "--seed", "4", "--share", "1"]  # fmt: skip
    assert cli.main(arguments) == 0
    items = json.loads((bundle / "items.json").read_text(encoding="utf-8"))
    assert len(items) == 6 and "type" not in items[0]
    assert (bundle / "grading-guide.md").exists()

    def post(url: str, **kwargs: Any) -> httpx.Response:
        content = json.dumps({"verdict": "sound", "reason": "ok"})
        body = {"choices": [{"message": {"content": content}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.CLIENT, "post", post)
    second = tmp_path / "gemma.json"
    assert cli.main(["grade-with-model", str(bundle / "items.json"),
                     "http://127.0.0.1:8083", "--out", str(second)]) == 0  # fmt: skip
    assert "6 items graded" in capsys.readouterr().out
    assert cli.main(["agreement", str(sitting / "verdicts.json"), str(second)]) == 0
    assert json.loads(capsys.readouterr().out)["agreed"] == 6

    names = [item["item"] for item in items]
    split = {names[0]: "partial", names[1]: "wrong"}  # no majority; a majority of wrong
    (tmp_path / "third.json").write_text(json.dumps(
        {name: {"verdict": "wrong", "reason": "r"} for name in names}))  # fmt: skip
    (tmp_path / "fourth.json").write_text(json.dumps(
        {name: {"verdict": split.get(name, "sound"), "reason": "r"}
         for name in names}))  # fmt: skip
    final = tmp_path / "final.json"
    arguments = ["settle", str(sitting), str(tmp_path / "third.json"),
                 str(tmp_path / "fourth.json"), "--out", str(final)]  # fmt: skip
    assert cli.main(arguments) == 1
    assert names[0] in capsys.readouterr().err
    settled = tmp_path / "settled.json"
    settled.write_text(json.dumps({names[0]: {"verdict": "wrong", "reason": "r"}}))
    assert cli.main([*arguments, "--settled", str(settled)]) == 0
    assert "2 verdicts changed" in capsys.readouterr().out

    claims = {f"{p['id']}/A": ["correct"] for p in pairs_written}
    (sitting / "claims.json").write_text(json.dumps(claims), encoding="utf-8")
    assert cli.main([*base, "reliability", "demo", *runs, "--dir", str(sitting),
                     "--verdicts", str(final), "--out", str(out)]) == 0  # fmt: skip
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert sum(arm["precision"]["of"] for arm in saved["claims"].values()) >= 4

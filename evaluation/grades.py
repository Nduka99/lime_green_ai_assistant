"""Count graded answers per arm: overall, by case type and by wording style.

A grading sitting is a folder holding `grades.json` ({question id: {arm:
{"verdict": "sound" | "partial" | "wrong", "reason": ...}}}) and one
`answers-<arm>.json` per arm, the answers as the endpoint returned them. The
automatic status match and the median time come from the saved answers, so they
are reported beside the grades rather than decided by the grader.
"""

import json
import statistics
from pathlib import Path
from typing import Any

VERDICTS = ("sound", "partial", "wrong")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def case_wordings(case: dict[str, Any]) -> list[dict[str, str]]:
    """A case's wordings: `wordings` in the held-out keys, `questions` in frozen90's."""
    found: list[dict[str, str]] = case.get("wordings") or case.get("questions", [])
    return found


def expected_statuses(case: dict[str, Any]) -> set[str]:
    """The statuses the key accepts: one in the held-out keys, a list in frozen90's."""
    expected = case["expected_status"]
    return set(expected) if isinstance(expected, list) else {expected}


def cases_by_question(
    key: dict[str, Any], questions: list[dict[str, str]]
) -> dict[str, tuple[dict[str, Any], str]]:
    """Blind question id -> (its case in the key, its wording style).

    Questions are matched to the key by their exact text, so the mapping does not
    depend on how the blind file was shuffled.
    """
    wordings: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for case in key["cases"]:
        for wording in case_wordings(case):
            wordings.setdefault(wording["text"], []).append((case, wording["style"]))
    found = {}
    for row in questions:
        matches = wordings.get(row["question"], [])
        if len(matches) != 1:
            raise ValueError(f"{row['id']} matches {len(matches)} wordings in the key")
        found[row["id"]] = matches[0]
    return found


def load_sitting(folder: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The sitting's grades and each graded arm's answers by question id."""
    grades: dict[str, Any] = read_json(folder / "grades.json")
    arms = list(next(iter(grades.values())))
    answers = {
        arm: {r["id"]: r for r in read_json(folder / f"answers-{arm}.json")}
        for arm in arms
    }
    return grades, answers


def counts(verdicts: list[str]) -> dict[str, int]:
    unknown = set(verdicts) - set(VERDICTS)
    if unknown:
        raise ValueError(f"unknown verdicts: {sorted(unknown)}")
    return {verdict: verdicts.count(verdict) for verdict in VERDICTS}


def status(record: dict[str, Any]) -> str:
    """The answer's status; an error record has none."""
    return str(record.get("view", {}).get("status", "error"))


def score(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    grades: dict[str, Any],
    answers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Verdict counts per group and arm, status matches, cautions and median time."""
    cases = cases_by_question(key, questions)
    ids = [row["id"] for row in questions]
    arms = list(answers)
    groups = []
    for name, qids in group_ids(cases, ids).items():
        per_arm = {}
        for arm in arms:
            per_arm[arm] = counts([grades[qid][arm]["verdict"] for qid in qids])
        groups.append({"name": name, "answers": len(qids), "counts": per_arm})
    result: dict[str, Any] = {
        "arms": arms,
        "groups": groups,
        "status_matched": {},
        "cautions": {},
        "median_seconds": {},
        "questions": len(ids),
    }
    for arm in arms:
        matched, cautions, seconds = arm_totals(answers[arm], cases, ids)
        result["status_matched"][arm] = matched
        result["cautions"][arm] = cautions
        result["median_seconds"][arm] = seconds
    return result


def group_ids(
    cases: dict[str, tuple[dict[str, Any], str]], ids: list[str]
) -> dict[str, list[str]]:
    """Question ids for "All", then per case type, then per wording style."""
    groups: dict[str, list[str]] = {"All": ids}
    for qid in ids:
        groups.setdefault(f"Type: {cases[qid][0]['type']}", []).append(qid)
    for qid in ids:
        groups.setdefault(f"Wording: {cases[qid][1]}", []).append(qid)
    return groups


def arm_totals(
    records: dict[str, dict[str, Any]],
    cases: dict[str, tuple[dict[str, Any], str]],
    ids: list[str],
) -> tuple[int, int, float]:
    """One arm's status matches, answers with a caution, and median seconds."""
    matched = 0
    cautions = 0
    for qid in ids:
        record = records[qid]
        if status(record) in expected_statuses(cases[qid][0]):
            matched += 1
        if record.get("view", {}).get("notice"):
            cautions += 1
    seconds = statistics.median(records[qid]["seconds"] for qid in ids)
    return matched, cautions, seconds


def markdown(result: dict[str, Any], title: str) -> str:
    arms = result["arms"]
    lines = [
        f"{title}: {result['questions']} answers per arm, sound / partial / wrong.",
        "",
        "| Group | Answers | " + " | ".join(arms) + " |",
        "|---|---|" + "---|" * len(arms),
    ]
    for group in result["groups"]:
        cells = [
            " / ".join(str(group["counts"][arm][v]) for v in VERDICTS) for arm in arms
        ]
        lines.append(
            f"| {group['name']} | {group['answers']} | " + " | ".join(cells) + " |"
        )
    lines += [
        "",
        "| Arm | Status as the key expects | Cautions | Median seconds |",
        "|---|---|---|---|",
    ]
    for arm in arms:
        lines.append(
            f"| {arm} | {result['status_matched'][arm]}/{result['questions']} | "
            f"{result['cautions'][arm]} | {result['median_seconds'][arm]:.1f} |"
        )
    return "\n".join(lines) + "\n"

"""Compare two runs of one set, question by question.

Where both runs show the reader the same answer, they score the same, so only the
other questions can show a difference between the systems (as in McNemar's test).
Those are written for blind grading, each pair with the runs' names hidden and in
shuffled order. Once graded, the differences are summed per case, because a case's
wordings are related, and a bootstrap over cases gives their interval (Miller 2024,
"Adding Error Bars to Evals", recommendations 2 and 4).
"""

import random
from typing import Any

from evaluation import grades, metrics

Records = dict[str, dict[str, Any]]  # an answers file by question id
SLOTS = ("A", "B")


def shown(record: dict[str, Any]) -> Any:
    """What the reader saw: the answer's view, or the error the endpoint returned."""
    return record.get("view", {"error": record.get("error")})


def differing(first: Records, second: Records, ids: list[str]) -> list[str]:
    """Question ids whose two answers differ in what the reader sees."""
    return [qid for qid in ids if shown(first[qid]) != shown(second[qid])]


def blind(
    ids: list[str], runs: dict[str, Records], seed: int
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """The two answers to each question as "A" and "B" in shuffled order, and that
    order by question id, kept apart until every pair is graded."""
    rng = random.Random(seed)
    pairs = []
    order = {}
    for qid in ids:
        names = list(runs)
        rng.shuffle(names)
        order[qid] = names
        pair: dict[str, Any] = {"id": qid, "question": runs[names[0]][qid]["question"]}
        for slot, name in zip(SLOTS, names, strict=True):
            pair[slot] = shown(runs[name][qid])
        pairs.append(pair)
    return pairs, order


def unblind(
    verdicts: dict[str, dict[str, Any]], order: dict[str, list[str]]
) -> dict[str, dict[str, Any]]:
    """Blind verdicts ({id: {"A": grade, "B": grade}}) as grades by run name, the
    shape of a sitting's grades.json."""
    graded = {}
    for qid, pair in verdicts.items():
        names = zip(SLOTS, order[qid], strict=True)
        graded[qid] = {name: pair[slot] for slot, name in names}
    return graded


def difference(
    graded: dict[str, dict[str, Any]],
    cases: dict[str, tuple[dict[str, Any], str]],
    case_ids: list[str],
    baseline: str,
    candidate: str,
    verdict: str,
) -> dict[str, float]:
    """The candidate's count of `verdict` minus the baseline's, with a 95% interval
    from resampling cases (a case with no graded pair contributes zero)."""
    per_case = dict.fromkeys(case_ids, 0)
    for qid, runs in graded.items():
        case_id = cases[qid][0]["id"]
        per_case[case_id] += int(runs[candidate]["verdict"] == verdict)
        per_case[case_id] -= int(runs[baseline]["verdict"] == verdict)
    values = [float(value) for value in per_case.values()]
    test = metrics.paired_bootstrap(values, [0.0] * len(values))
    scale = len(values)  # the bootstrap gives a mean per case; report totals
    return {
        "difference": sum(values),
        "low": test["low"] * scale,
        "high": test["high"] * scale,
    }


def compare(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    runs: dict[str, Records],
    graded: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Status matches and safety referrals for every question, and the graded
    differences in sound and wrong answers; the second run is the candidate."""
    baseline, candidate = list(runs)
    cases = grades.cases_by_question(key, questions)
    ids = [row["id"] for row in questions]
    emergencies = [
        qid
        for qid in ids
        if "safety_referral" in grades.expected_statuses(cases[qid][0])
    ]
    result: dict[str, Any] = {
        "runs": [baseline, candidate],
        "questions": len(ids),
        "differing": len(graded),
        "emergencies": len(emergencies),
        "status_matched": {},
        "referred": {},
    }
    for name, records in runs.items():
        matched = [
            qid
            for qid in ids
            if grades.status(records[qid]) in grades.expected_statuses(cases[qid][0])
        ]
        referred = [
            qid
            for qid in emergencies
            if grades.status(records[qid]) == "safety_referral"
        ]
        result["status_matched"][name] = len(matched)
        result["referred"][name] = len(referred)
    case_ids = [case["id"] for case in key["cases"]]
    for verdict in ("sound", "wrong"):
        result[verdict] = difference(
            graded, cases, case_ids, baseline, candidate, verdict
        )
    return result


def markdown(result: dict[str, Any]) -> str:
    baseline, candidate = result["runs"]
    total = result["questions"]
    lines = [
        f"| | {baseline} | {candidate} |",
        "|---|---|---|",
        "| Status as the key expects | "
        f"{result['status_matched'][baseline]}/{total} | "
        f"{result['status_matched'][candidate]}/{total} |",
        "| Safety referral on emergency questions | "
        f"{result['referred'][baseline]}/{result['emergencies']} | "
        f"{result['referred'][candidate]}/{result['emergencies']} |",
        "",
        f"Answers that differ: {result['differing']} of {total}, graded blind.",
        "",
        f"| Verdict | {candidate} minus {baseline} | 95% interval, cases resampled |",
        "|---|---|---|",
    ]
    for verdict in ("sound", "wrong"):
        found = result[verdict]
        lines.append(
            f"| {verdict} | {found['difference']:+.0f} | "
            f"{found['low']:+.1f} to {found['high']:+.1f} |"
        )
    return "\n".join(lines) + "\n"

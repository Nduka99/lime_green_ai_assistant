"""Compare runs of one set, question by question.

Where runs show the reader the same answer, they score the same, so only the other
questions can show a difference between the systems (as in McNemar's test). For
those, each distinct answer is written once for blind grading, under a letter, with
the runs' names hidden and the letters shuffled. Once graded, the differences are
summed per case, because a case's wordings are related, and a bootstrap over cases
gives their interval (Miller 2024, "Adding Error Bars to Evals", recommendations 2
and 4).
"""

import json
import random
from typing import Any

from evaluation import grades, metrics

Records = dict[str, dict[str, Any]]  # an answers file by question id
SLOTS = tuple("ABCDEFGH")  # one letter per distinct answer to a question


def shown(record: dict[str, Any]) -> Any:
    """What the reader saw: the answer's view, or the error the endpoint returned."""
    return record.get("view", {"error": record.get("error")})


def differing(runs: dict[str, Records], ids: list[str]) -> list[str]:
    """Question ids whose runs do not all show the reader the same answer."""
    found = []
    for qid in ids:
        views = [shown(records[qid]) for records in runs.values()]
        if any(view != views[0] for view in views):
            found.append(qid)
    return found


def distinct(runs: dict[str, Records], qid: str) -> list[list[str]]:
    """The runs grouped by the answer they show to one question, in run order."""
    groups: dict[str, list[str]] = {}
    for name, records in runs.items():
        groups.setdefault(json.dumps(shown(records[qid]), sort_keys=True), []).append(
            name
        )
    return list(groups.values())


def blind(
    ids: list[str], runs: dict[str, Records], seed: int
) -> tuple[list[dict[str, Any]], dict[str, list[list[str]]]]:
    """Each question's distinct answers under the letters "A", "B", ... in shuffled
    order, and which runs showed each letter's answer, kept apart until every
    answer is graded."""
    rng = random.Random(seed)
    pairs = []
    order = {}
    for qid in ids:
        groups = distinct(runs, qid)
        rng.shuffle(groups)
        order[qid] = groups
        first = runs[groups[0][0]][qid]
        pair: dict[str, Any] = {"id": qid, "question": first["question"]}
        for slot, names in zip(SLOTS, groups, strict=False):
            pair[slot] = shown(runs[names[0]][qid])
        pairs.append(pair)
    return pairs, order


def unblind(
    verdicts: dict[str, dict[str, Any]], order: dict[str, list[Any]]
) -> dict[str, dict[str, Any]]:
    """Blind verdicts ({id: {"A": grade, "B": grade, ...}}) as grades by run name,
    the shape of a sitting's grades.json. An order entry is a list of run names per
    letter; sittings written before multi-run blinding hold one name per letter."""
    graded: dict[str, dict[str, Any]] = {}
    for qid, pair in verdicts.items():
        graded[qid] = {}
        for slot, entry in zip(SLOTS, order[qid], strict=False):
            for name in [entry] if isinstance(entry, str) else entry:
                graded[qid][name] = pair[slot]
    return graded


COUNTED = ("sound", "wrong", "missing")  # the differences every comparison reports


def counted(verdict: str, name: str) -> bool:
    """Whether a verdict counts as `name`. "sound" and "wrong" are counted on the
    three-level scale of the sittings before "missing" existed (`grades.legacy`), so
    a refused answerable question is wrong there, as S2's gate counted it; "missing"
    counts those refusals on their own."""
    if name == "missing":
        return verdict == "missing"
    return grades.legacy(verdict) == name


def difference(
    graded: dict[str, dict[str, Any]],
    cases: dict[str, tuple[dict[str, Any], str]],
    case_ids: list[str],
    baseline: str,
    candidate: str,
    verdict: str,
) -> dict[str, float]:
    """The candidate's count of `verdict` (see `counted`) minus the baseline's, with a
    95% interval from resampling cases (a case with no graded pair contributes zero)."""
    per_case = dict.fromkeys(case_ids, 0)
    for qid, runs in graded.items():
        case_id = cases[qid][0]["id"]
        per_case[case_id] += int(counted(runs[candidate]["verdict"], verdict))
        per_case[case_id] -= int(counted(runs[baseline]["verdict"], verdict))
    values = [float(value) for value in per_case.values()]
    test = metrics.paired_bootstrap(values, [0.0] * len(values))
    scale = len(values)  # the bootstrap gives a mean per case; report totals
    return {
        "difference": sum(values),
        "low": test["low"] * scale,
        "high": test["high"] * scale,
    }


def score_difference(
    graded: dict[str, dict[str, Any]],
    cases: dict[str, tuple[dict[str, Any], str]],
    ids: list[str],
    baseline: str,
    candidate: str,
) -> dict[str, float]:
    """The mean CRAG score per case, candidate minus baseline, with a 95% interval
    from resampling cases. A case's score is the mean over its questions, and a
    question whose answers were not graded (both runs showed the same) adds zero."""
    per_case: dict[str, float] = {}
    size: dict[str, int] = {}
    for qid in ids:
        case_id = cases[qid][0]["id"]
        size[case_id] = size.get(case_id, 0) + 1
        per_case.setdefault(case_id, 0.0)
        if qid in graded:
            new = grades.SCORES[graded[qid][candidate]["verdict"]]
            old = grades.SCORES[graded[qid][baseline]["verdict"]]
            per_case[case_id] += new - old
    values = [per_case[case_id] / size[case_id] for case_id in per_case]
    test = metrics.paired_bootstrap(values, [0.0] * len(values))
    return {"difference": test["difference"], "low": test["low"], "high": test["high"]}


def compare(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    runs: dict[str, Records],
    graded: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Status matches and safety referrals for every question, and the graded
    differences between two runs; the second run is the candidate. `graded` may hold
    other runs' verdicts too, from a sitting that graded more than two runs."""
    baseline, candidate = list(runs)
    cases = grades.cases_by_question(key, questions)
    ids = [row["id"] for row in questions]
    graded = {qid: graded[qid] for qid in differing(runs, ids) if qid in graded}
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
    for verdict in COUNTED:
        result[verdict] = difference(
            graded, cases, case_ids, baseline, candidate, verdict
        )
    result["score"] = score_difference(graded, cases, ids, baseline, candidate)
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
    for verdict in COUNTED:
        found = result[verdict]
        lines.append(
            f"| {verdict} | {found['difference']:+.0f} | "
            f"{found['low']:+.1f} to {found['high']:+.1f} |"
        )
    score = result["score"]
    lines += [
        f"| score per case (CRAG) | {score['difference']:+.3f} | "
        f"{score['low']:+.3f} to {score['high']:+.3f} |",
        "",
        "Wrong includes answerable questions refused (S2's three-level scale); missing"
        " counts those alone. CRAG scores sound 1, partial 0.5, missing 0, wrong -1.",
    ]
    return "\n".join(lines) + "\n"

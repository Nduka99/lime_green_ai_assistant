"""Answer reliability (R0, D98): what a customer relying on the answers is exposed to.

Every measure counts cases, not wordings: a case's wordings are ways of asking one
thing, so they are not independent (Miller 2024). From one set's key, each arm's
answers and the graded verdicts (`{question id: {arm: {"verdict": ...}}}`):

- risk: cases with an answer given (status `answered`) that was graded wrong, over cases
  with an answer given, with its Wilson 95% upper bound (the release bar, R1);
- coverage: answerable cases whose every wording was graded sound or partial;
- refusals: cases the key expects refused whose every wording was refused;
- emergencies: cases the key expects referred whose every wording was referred;
- consistency: cases with several wordings whose wordings got one verdict;
- attribution: why each answerable wording fell short (from `evaluation reach` rows).
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from evaluation import grades, metrics

ANSWERED = "answered"
REFUSED = "insufficient_evidence"
REFERRED = "safety_referral"
SHORT = ("partial", "missing", "wrong")  # an answerable question not answered soundly

Row = dict[str, Any]


def case_rows(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    graded: dict[str, dict[str, Any]],
    records: dict[str, dict[str, dict[str, Any]]],
) -> list[Row]:
    """One row per arm and case: its type, the statuses the key accepts, and each
    wording's question id, status and verdict."""
    cases = grades.cases_by_question(key, questions)
    by_case: dict[str, list[str]] = {}
    for row in questions:
        by_case.setdefault(cases[row["id"]][0]["id"], []).append(row["id"])
    rows = []
    for arm, answers in records.items():
        for case_id, ids in by_case.items():
            case = cases[ids[0]][0]
            rows.append({
                "arm": arm,
                "case": case_id,
                "type": case["type"],
                "expected": sorted(grades.expected_statuses(case)),
                "ids": ids,
                "statuses": [grades.status(answers[qid]) for qid in ids],
                "verdicts": [graded[qid][arm]["verdict"] for qid in ids],
            })  # fmt: skip
    return rows


def share(found: int, total: int) -> dict[str, Any]:
    """A count out of a total, its share and the share's Wilson 95% bounds."""
    low, high = metrics.wilson(found, total)
    return {"count": found, "of": total, "share": found / total if total else 0.0,
            "low": low, "high": high}  # fmt: skip


def summary(rows: Sequence[Row]) -> dict[str, Any]:
    """Risk, coverage, refusals, emergencies and consistency over one arm's rows."""
    given = [r for r in rows if ANSWERED in r["statuses"]]
    wrong = [
        r
        for r in given
        if any(
            status == ANSWERED and verdict == "wrong"
            for status, verdict in zip(r["statuses"], r["verdicts"], strict=True)
        )
    ]
    answerable = [r for r in rows if r["expected"] == [ANSWERED]]
    covered = [
        r for r in answerable if all(v in ("sound", "partial") for v in r["verdicts"])
    ]
    refusable = [r for r in rows if r["expected"] == [REFUSED]]
    refused = [r for r in refusable if all(s == REFUSED for s in r["statuses"])]
    urgent = [r for r in rows if REFERRED in r["expected"]]
    referred = [r for r in urgent if all(s == REFERRED for s in r["statuses"])]
    worded = [r for r in rows if len(r["ids"]) > 1]
    consistent = [r for r in worded if len(set(r["verdicts"])) == 1]
    return {
        "cases": len(rows),
        "risk": share(len(wrong), len(given)),
        "coverage": share(len(covered), len(answerable)),
        "refusals": share(len(refused), len(refusable)),
        "emergencies": share(len(referred), len(urgent)),
        "consistency": share(len(consistent), len(worded)),
        "wrong_cases": [r["case"] for r in wrong],
    }


def by_arm(rows: Sequence[Row]) -> dict[str, dict[str, Any]]:
    """Each arm's summary, overall and per case type."""
    found: dict[str, dict[str, Any]] = {}
    for arm in dict.fromkeys(r["arm"] for r in rows):
        mine = [r for r in rows if r["arm"] == arm]
        types = {
            kind: summary([r for r in mine if r["type"] == kind])
            for kind in sorted({r["type"] for r in mine})
        }
        found[arm] = {"all": summary(mine), "types": types}
    return found


def coverage_difference(
    rows: Sequence[Row], arm: str, baseline: str
) -> dict[str, float]:
    """The arm's coverage minus the baseline's on the same answerable cases, with a
    95% interval from resampling cases (R1 item 4)."""

    def covered(name: str) -> dict[str, float]:
        return {
            r["case"]: float(all(v in ("sound", "partial") for v in r["verdicts"]))
            for r in rows
            if r["arm"] == name and r["expected"] == [ANSWERED]
        }

    new, old = covered(arm), covered(baseline)
    cases = sorted(new)
    return metrics.paired_bootstrap([new[c] for c in cases], [old[c] for c in cases])


def attribution(
    rows: Sequence[Row], reached: dict[str, dict[str, list[bool]]]
) -> dict[str, dict[str, int]]:
    """Per arm, why each answerable wording fell short: "retrieval" when some part's
    evidence never reached the model's passages, "generation" when every part's did.
    `reached` is {arm: {question id: [reached per part]}} from `evaluation reach`."""
    found: dict[str, Counter[str]] = {}
    for row in rows:
        counts = found.setdefault(row["arm"], Counter())
        if row["expected"] != [ANSWERED]:
            continue
        for qid, verdict in zip(row["ids"], row["verdicts"], strict=True):
            if verdict not in SHORT:
                continue
            parts = reached.get(row["arm"], {}).get(qid, [])
            cause = "retrieval" if parts and not all(parts) else "generation"
            counts[f"{verdict} by {cause}"] += 1
    return {arm: dict(sorted(counts.items())) for arm, counts in found.items()}


def reached_parts(reach_rows: Sequence[dict[str, Any]]) -> dict[str, list[bool]]:
    """{question id: [reached per part]} from the rows of one `evaluation reach --out`
    file."""
    found: dict[str, list[bool]] = {}
    for row in reach_rows:
        found.setdefault(row["id"], []).append(bool(row["reached"]))
    return found


def claim_precision(labels: dict[str, list[str]]) -> dict[str, Any]:
    """Shown claims labelled correct over all shown claims, with each label's count
    (labels: correct, off_question, incorrect, forbidden)."""
    counts = Counter(label for claims in labels.values() for label in claims)
    total = sum(counts.values())
    return {"labels": dict(sorted(counts.items())),
            "precision": share(counts["correct"], total)}  # fmt: skip


def claims_by_arm(
    labels: dict[str, list[str]], order: dict[str, list[list[str]]]
) -> dict[str, dict[str, list[str]]]:
    """Claim labels by blind item ("<question id>/<letter>") as {arm: {question id:
    labels}}, through the sitting's order (the runs that showed each letter)."""
    found: dict[str, dict[str, list[str]]] = {}
    for item, claims in labels.items():
        qid, slot = item.split("/")
        for arm in order[qid][ord(slot) - ord("A")]:
            found.setdefault(arm, {})[qid] = claims
    return found

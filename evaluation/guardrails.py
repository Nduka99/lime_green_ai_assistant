"""Checks every run must pass on every index version before it goes live (X16).

They are read by code from what the reader was shown, so they need no grading:

- no answer shows a price anywhere (claims, quotes, notices, listed pages);
- every question the key marks as an emergency gets the fixed safety referral.

How many of the questions the key expects refused were refused is reported
beside them. Results name question ids only, never answer text.
"""

import json
from typing import Any

from evaluation import grades, pairs
from limespec import prices


def check(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The guardrail results for one run of one set."""
    cases = grades.cases_by_question(key, questions)
    ids = [row["id"] for row in questions]
    priced = []
    emergencies = []
    missed = []
    refusals = []
    refused = []
    for qid in ids:
        record = records[qid]
        # ensure_ascii=False keeps "£" as itself, where the price rule can see it.
        if prices.states_price(json.dumps(pairs.shown(record), ensure_ascii=False)):
            priced.append(qid)
        expected = grades.expected_statuses(cases[qid][0])
        if "safety_referral" in expected:
            emergencies.append(qid)
            if grades.status(record) != "safety_referral":
                missed.append(qid)
        if expected == {"insufficient_evidence"}:
            refusals.append(qid)
            if grades.status(record) == "insufficient_evidence":
                refused.append(qid)
    return {
        "questions": len(ids),
        "priced": priced,
        "emergencies": len(emergencies),
        "missed": missed,
        "refusals": len(refusals),
        "refused": len(refused),
    }


def passed(result: dict[str, Any]) -> bool:
    """No price shown and no emergency missed."""
    return not result["priced"] and not result["missed"]


def text(result: dict[str, Any]) -> str:
    """One summary line, then one line per failing question."""
    lines = [
        f"{result['questions']} answers: {len(result['priced'])} show a price; "
        f"{result['emergencies'] - len(result['missed'])}/{result['emergencies']} "
        f"emergencies referred; {result['refused']}/{result['refusals']} expected "
        "refusals refused"
    ]
    lines += [f"PRICE {qid}" for qid in result["priced"]]
    lines += [f"MISSED EMERGENCY {qid}" for qid in result["missed"]]
    return "\n".join(lines)

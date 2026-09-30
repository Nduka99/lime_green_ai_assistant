"""The claim benchmark for the sufficiency gate (E5 stage C).

Every claim shown in a graded run's answers was labelled in its claim audit: correct,
off the question, incorrect or forbidden. Here each distinct claim becomes one item:
its question, the question's parts, the claim, the quotes it cites and its label. A
candidate detector gives every item a score, higher meaning "more likely correct", and
is judged by how well the score separates the labels (ROC AUC) and by a threshold
chosen on one half of the cases and tested on the other.

The threshold is set by conformal risk control (Angelopoulos et al. 2024): the largest
value whose share of correct claims withheld, corrected for the size of the
calibration half, stays within `ALPHA`. Cases, not claims, are split, because a case's
claims are related.
"""

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from evaluation import grades, metrics, pairs

Item = dict[str, Any]
CORRECT = "correct"
ALPHA = 0.1  # correct claims the gate may withhold: at most 1 in 10
CAUGHT = 0.5  # claims that are not correct it must withhold: at least half


def items(
    name: str,
    key: dict[str, Any],
    questions: list[dict[str, str]],
    blinded: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Sequence[str]],
    parts: Mapping[str, Sequence[str]],
) -> list[Item]:
    """One item per distinct claim of a set's blind answers. `labels` holds the claim
    audit ({"<question>/<letter>": [label per claim]}); `parts` the search questions
    a replay wrote per question (a question without them is its own single part)."""
    cases = grades.cases_by_question(key, questions)
    found: dict[tuple[str, str], Item] = {}
    for pair in blinded:
        qid = pair["id"]
        for slot in pairs.SLOTS:
            view = pair.get(slot) or {}
            claims = view.get("claims") or []
            if not claims:
                continue
            quotes = {source["number"]: source["quote"] for source in view["sources"]}
            audit = labels[f"{qid}/{slot}"]
            for number, (claim, label) in enumerate(zip(claims, audit, strict=True), 1):
                found.setdefault(
                    (qid, claim["text"]),
                    {
                        "id": f"{name}/{qid}/{slot}{number}",
                        "case": f"{name}/{cases[qid][0]['id']}",
                        "question": pair["question"],
                        "parts": list(parts.get(qid) or [pair["question"]]),
                        "claim": claim["text"],
                        "quotes": [quotes[n] for n in claim["sources"]],
                        "label": label,
                    },
                )
    return list(found.values())


def halves(found: Sequence[Item], seed: int) -> tuple[list[Item], list[Item]]:
    """The items of a seeded half of the cases (calibration), and the rest (test)."""
    names = sorted({item["case"] for item in found})
    random.Random(seed).shuffle(names)
    first = set(names[: len(names) // 2])
    return (
        [item for item in found if item["case"] in first],
        [item for item in found if item["case"] not in first],
    )


def threshold(correct_scores: Sequence[float], alpha: float = ALPHA) -> float:
    """The largest threshold that withholds (scores below it) at most `alpha` of the
    correct claims, with conformal risk control's correction for a finite sample:
    (n x the share withheld + 1) / (n + 1) <= alpha. Minus infinity when even the
    lowest score cannot be withheld (too few claims to calibrate on)."""
    ordered = sorted(correct_scores)
    size = len(ordered)
    allowed = math.floor(alpha * (size + 1) - 1)  # correct claims that may fall below
    if allowed < 0:
        return float("-inf")
    # Scores strictly below the threshold are withheld: put it at the score of the
    # first claim that must stay.
    return ordered[min(allowed, size - 1)]


def score(
    found: Sequence[Item], scores: Mapping[str, float], seed: int
) -> dict[str, Any]:
    """How a detector's scores separate the labels, and whether it qualifies at the
    threshold set on the calibration half and tested on the other."""
    calibration, test = halves(found, seed)
    cut = threshold(
        [scores[item["id"]] for item in calibration if item["label"] == CORRECT]
    )
    good = [item for item in test if item["label"] == CORRECT]
    bad = [item for item in test if item["label"] != CORRECT]
    withheld = sum(scores[item["id"]] < cut for item in good)
    caught = sum(scores[item["id"]] < cut for item in bad)
    by_label: dict[str, list[int]] = {}
    for item in bad:
        tally = by_label.setdefault(item["label"], [0, 0])
        tally[0] += scores[item["id"]] < cut
        tally[1] += 1
    separates = [(scores[item["id"]], item["label"] == CORRECT) for item in found]
    withheld_share = withheld / len(good) if good else 0.0
    caught_share = caught / len(bad) if bad else 0.0
    return {
        "auc": metrics.auc(separates),
        "threshold": cut,
        "correct_withheld": {
            "count": withheld,
            "of": len(good),
            "share": withheld_share,
        },
        "not_correct_caught": {"count": caught, "of": len(bad), "share": caught_share},
        "caught_by_label": {
            k: {"count": v[0], "of": v[1]} for k, v in by_label.items()
        },
        "qualifies": withheld_share <= ALPHA and caught_share >= CAUGHT,
    }

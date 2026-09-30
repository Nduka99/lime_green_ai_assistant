"""Second graders (R0, D98): every grader sees the same blind items and the same guide.

An item is one distinct answer to one question, as `evaluation blind` wrote it under a
letter, with the key's expected status, answer, parts and `must_not` rules beside it and
no run name. A sample for second graders is drawn per case type, and always includes
every item the primary grader judged wrong or missing, since the release bar rests on
those. A local model grades items through the same chat request as the assistant's own
calls; an outside grader gets the items and guide as files.
"""

import json
import math
import random
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from evaluation import grades, metrics
from limespec import config, llm

GUIDE = Path(__file__).parent / "briefs" / "grading-guide.md"
SLOTS = "ABCDEFGH"
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(grades.VERDICTS)},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}
Item = dict[str, Any]
Send = Callable[[dict[str, Any]], dict[str, Any]]


def key_view(case: dict[str, Any]) -> dict[str, Any]:
    """What a grader needs from a case: the held-out keys' fields, or frozen90's
    (whose parts give `answer` rather than `expected_answer`)."""
    return {
        "expected_status": sorted(grades.expected_statuses(case)),
        "expected_answer": case.get("expected_answer", ""),
        "parts": [
            {
                "asks": part.get("asks", ""),
                "expected_answer": part.get("expected_answer", part.get("answer")),
            }
            for part in case.get("parts", [])
        ],  # fmt: skip
        "must_not": case.get("must_not", []),
    }


def answer_view(shown: dict[str, Any]) -> dict[str, Any]:
    """What the customer saw: status, notice and the claims' text."""
    if "error" in shown:
        return {"status": "error", "notice": "", "claims": []}
    return {
        "status": shown.get("status", ""),
        "notice": shown.get("notice", ""),
        "claims": [claim["text"] for claim in shown.get("claims", [])],
    }


def items(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    blinded: Sequence[dict[str, Any]],
) -> list[Item]:
    """One item per distinct answer in `evaluation blind`'s pairs, named
    "<question id>/<letter>"."""
    cases = grades.cases_by_question(key, questions)
    found = []
    for pair in blinded:
        case = cases[pair["id"]][0]
        for slot in SLOTS:
            if slot in pair:
                found.append({
                    "item": f"{pair['id']}/{slot}",
                    "type": case["type"],
                    "question": pair["question"],
                    "key": key_view(case),
                    "answer": answer_view(pair[slot]),
                })  # fmt: skip
    return found


def flat(verdicts: dict[str, Any]) -> dict[str, str]:
    """Verdicts by item: from a blind sitting's {question: {letter: grade}} or a second
    grader's {item: grade}."""
    found = {}
    for name, grade in verdicts.items():
        if "verdict" in grade:
            found[name] = grade["verdict"]
        else:
            for slot, inner in grade.items():
                found[f"{name}/{slot}"] = inner["verdict"]
    return found


def sample(
    found: Sequence[Item], primary: dict[str, str], share: float, seed: int
) -> list[Item]:
    """A share of the items from each case type, drawn with `seed`, plus every item the
    primary grader judged wrong or missing; in the items' order."""
    rng = random.Random(seed)
    chosen = {
        i["item"] for i in found if primary.get(i["item"]) in ("wrong", "missing")
    }
    for kind in sorted({i["type"] for i in found}):
        names = sorted(i["item"] for i in found if i["type"] == kind)
        chosen.update(rng.sample(names, math.ceil(share * len(names))))
    return [i for i in found if i["item"] in chosen]


def grader_prompt(item: Item) -> str:
    """One item as the grader reads it (no run names, no case type)."""
    shown = {"question": item["question"], "key": item["key"], "answer": item["answer"]}
    return json.dumps(shown, indent=1, ensure_ascii=False)


def post_to(url: str) -> Send:
    """A chat request to the model server at `url`, through the shared client."""

    def send(body: dict[str, Any]) -> dict[str, Any]:
        response = llm.CLIENT.post(
            url.rstrip("/") + "/v1/chat/completions",
            json=body,
            headers=llm.auth(),
            timeout=config.CHAT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        reply: dict[str, Any] = response.json()
        return reply

    return send


def grade(found: Sequence[Item], guide: str, send: Send) -> dict[str, dict[str, str]]:
    """Each item's verdict and reason from a model grading by the guide."""
    verdicts = {}
    for item in found:
        body = llm.chat_payload(guide, grader_prompt(item), VERDICT_SCHEMA)
        reply = send(body)
        verdict = json.loads(reply["choices"][0]["message"]["content"])
        verdicts[item["item"]] = {
            "verdict": verdict["verdict"],
            "reason": verdict["reason"],
        }
    return verdicts


def agreement(first: dict[str, str], second: dict[str, str]) -> dict[str, Any]:
    """Cohen's κ and the table of verdict pairs over the items both graders judged."""
    shared = sorted(set(first) & set(second))
    a = [first[name] for name in shared]
    b = [second[name] for name in shared]
    table: dict[str, int] = {}
    for x, y in zip(a, b, strict=True):
        table[f"{x} / {y}"] = table.get(f"{x} / {y}", 0) + 1
    return {
        "items": len(shared),
        "agreed": sum(x == y for x, y in zip(a, b, strict=True)),
        "kappa": metrics.cohen_kappa(a, b) if shared else 0.0,
        "table": dict(sorted(table.items())),
    }

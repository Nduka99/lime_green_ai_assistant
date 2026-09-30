"""Relevance-check candidates measured offline (S2b, after C3 and C3′ failed).

The benchmark is built from a run's answers: each answer's verified claims with the
quotes they cite, and the question's parts from the first request, run again. Each
claim is labelled by reading, before any candidate is scored, with the part it
answers or 0. A candidate reads an item and returns one part number per claim; it
is scored on the claims it would wrongly remove (labelled as answering a part,
given 0) and the claims it would rightly remove (labelled 0, given 0).

Candidates:
- `c3`: C3's check (`88be48d`): a bare part number per claim.
- `c3p`: C3′'s check (`e51c294`): the part in its own words, then its number.
- `think128`, `think256`: C3′'s check with the model's thinking on, capped at 128 or
  256 tokens.
- `rerank`: the cross-encoder's score of each claim against each part; reported as how
  well the best score separates the two labels (ROC AUC), with no threshold.
"""

import json
import time
from collections.abc import Callable, Sequence
from string import ascii_uppercase
from typing import Any

from evaluation import metrics
from limespec import config, llm

C3_PROMPT = """\
You check the claims written to answer a question about Lime Green building \
products. You see the question's numbered parts, then each claim with the quotes it \
rests on. For each claim, in order, return the number of the part it states, or 0 \
if it states none.

A claim states a part when it gives what that part asks about the same product: \
the same property, quantity or unit. A related but different property, quantity or \
unit, or a different product, does not state it. A claim saying that the asked \
thing is absent or is not the case does state it."""
C3P_PROMPT = """\
You check the claims written to answer a question about Lime Green building \
products. You see the question's numbered parts, then each claim, lettered, with the \
quotes it rests on. For each claim, in order, first write the part it answers in \
that part's own words, or "none", then give that part's number, or 0 for none.

A claim answers a part when it gives what that part asks, or says it is absent or \
not the case. A statement about something the part does not ask (another quantity, \
unit, property or product) answers no part, even when it is true and about the \
same subject."""
# The model's thinking, capped at this many tokens, before its JSON reply.
BUDGETS = {"think128": 128, "think256": 256}
CANDIDATES = ("c3", "c3p", *BUDGETS, "rerank")

Item = dict[str, Any]
Post = Callable[[dict[str, Any]], dict[str, Any]]
Rerank = Callable[[str, list[str]], list[float]]


def items(
    records: Sequence[dict[str, Any]], understand: Callable[[str], list[str]]
) -> list[Item]:
    """Every answer with verified claims: its question, its parts, and each claim with
    the quotes it cites (from the sources the reader was shown)."""
    found = []
    for record in records:
        view = record.get("view") or {}
        if not view.get("claims"):
            continue
        quotes = {source["number"]: source["quote"] for source in view["sources"]}
        claims = [
            {"text": claim["text"], "quotes": [quotes[n] for n in claim["sources"]]}
            for claim in view["claims"]
        ]
        parts = understand(record["question"])
        found.append({"id": record["id"], "parts": parts, "claims": claims})
    return found


def user_prompt(item: Item, lettered: bool) -> str:
    """The numbered parts, then each claim with its quotes, numbered as C3 did or
    lettered as C3′ did."""
    parts = "\n".join(f"{n}. {part}" for n, part in enumerate(item["parts"], 1))
    marks = (
        (f"Claim {letter}:" for letter in ascii_uppercase)
        if lettered
        else (f"{n}." for n in range(1, len(item["claims"]) + 1))
    )
    lines = []
    for mark, claim in zip(marks, item["claims"], strict=False):
        quotes = "; ".join(f'"{quote}"' for quote in claim["quotes"])
        lines.append(f"{mark} {claim['text']}\n   Quotes: {quotes}")
    return f"Parts of the question:\n{parts}\n\nClaims:\n" + "\n".join(lines)


def schema(candidate: str, claims: int, parts: int) -> dict[str, Any]:
    """C3's schema (a bare number per claim) or C3′'s (words, then number)."""
    number = {"type": "integer", "minimum": 0, "maximum": parts}
    if candidate == "c3":
        items_schema: dict[str, Any] = number
        key = "parts"
    else:
        items_schema = {
            "type": "object",
            "properties": {
                "answers": {"type": "string", "minLength": 1},
                "part": number,
            },
            "required": ["answers", "part"],
            "additionalProperties": False,
        }
        key = "claims"
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "array",
                "minItems": claims,
                "maxItems": claims,
                "items": items_schema,
            }  # fmt: skip
        },
        "required": [key],
        "additionalProperties": False,
    }


def payload(candidate: str, item: Item) -> dict[str, Any]:
    """The chat request a model candidate sends for one item."""
    prompt = C3_PROMPT if candidate == "c3" else C3P_PROMPT
    body = llm.chat_payload(
        prompt,
        user_prompt(item, lettered=candidate != "c3"),
        schema(candidate, len(item["claims"]), len(item["parts"])),
    )
    body["cache_prompt"] = False
    if candidate in BUDGETS:
        body["chat_template_kwargs"] = {"enable_thinking": True}
        body["reasoning_budget_tokens"] = BUDGETS[candidate]
    return body


def parse(candidate: str, reply: dict[str, Any]) -> list[int]:
    """The part number per claim from a model candidate's reply."""
    output = json.loads(reply["choices"][0]["message"]["content"])
    if candidate == "c3":
        return list(output["parts"])
    return [check["part"] for check in output["claims"]]


def post(body: dict[str, Any]) -> dict[str, Any]:
    """One request to the generator, through the shared client."""
    response = llm.CLIENT.post(
        config.CHAT_URL,
        json=body,
        headers=llm.auth(),
        timeout=config.CHAT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    reply: dict[str, Any] = response.json()
    return reply


def check(
    candidate: str,
    found: Sequence[Item],
    send: Post = post,
    rerank: Rerank = llm.rerank,
) -> list[dict[str, Any]]:
    """Each item's result for one candidate, with the seconds it took: part numbers
    for a model candidate, the best score over the parts per claim for `rerank`."""
    results = []
    for item in found:
        started = time.perf_counter()
        if candidate == "rerank":
            texts = [claim["text"] for claim in item["claims"]]
            by_part = [rerank(part, texts) for part in item["parts"]]
            result: dict[str, Any] = {
                "scores": [max(s) for s in zip(*by_part, strict=True)]
            }
        else:
            result = {"parts": parse(candidate, send(payload(candidate, item)))}
        result.update(id=item["id"], seconds=time.perf_counter() - started)
        results.append(result)
    return results


def score(
    labels: dict[str, list[int]], results: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Claims wrongly and rightly removed (a model candidate), or how well the best
    score separates claims that answer a part from those that answer none (`rerank`),
    with the median seconds per item."""
    seconds = [result["seconds"] for result in results]
    found: dict[str, Any] = {
        "items": len(results),
        "median_seconds": metrics.median(seconds),
    }
    relevant = sum(1 for result in results for label in labels[result["id"]] if label)
    found.update(relevant=relevant, irrelevant=sum(
        1 for result in results for label in labels[result["id"]] if not label
    ))  # fmt: skip
    if "scores" in results[0]:
        pairs = [
            (score, bool(label))
            for result in results
            for score, label in zip(result["scores"], labels[result["id"]], strict=True)
        ]
        found["auc"] = metrics.auc(pairs)
        return found
    wrongly = rightly = other_part = 0
    for result in results:
        for given, label in zip(result["parts"], labels[result["id"]], strict=True):
            wrongly += bool(label) and given == 0
            rightly += not label and given == 0
            other_part += bool(label) and given not in (0, label)
    found.update(
        wrongly_removed=wrongly, rightly_removed=rightly, other_part=other_part
    )
    return found

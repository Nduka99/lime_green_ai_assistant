"""E7 S1: slot matching scored on the claim benchmark (`evaluation.claims`).

Each claim of `claims-dev` gets its sources back from the graded sittings (document
title, heading, quote); `limespec.slots` reads the slots every part asks for and every
source states; comparators score each claim by how well a stated slot meets an asked
one. Scores go to `evaluation claim-score` like E5's detectors.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from limespec import config, llm, scope, slots
from limespec.slots import Slot, Source

Item = dict[str, Any]
PairScore = Callable[[list[tuple[str, str]]], list[float]]  # phrase pairs to scores
BATCH = 8  # sources read in one request
STRIP = ' "[],'  # JSON around a yes or no token

JUDGE_PROMPT = """\
Each numbered pair has an asked slot (A) and a stated slot (B), each written as \
"subject: kind of information". For each pair, answer "yes" if B gives the kind of \
information A asks for, about the same subject, wholly or in part (such as one item of \
a list A asks for). Answer "no" if B gives a different kind of information, or the \
same kind about a different subject. Judge only the words given."""


def claim_sources(
    found: Sequence[Item], blinded: Mapping[str, Sequence[Item]]
) -> dict[str, list[Source]]:
    """Each claim's sources, from the blind pairs of its set (`blinded` by set name):
    the item id "set/question/<letter><claim number>" names the answer and claim."""
    views = {}
    for name, pairs in blinded.items():
        for pair in pairs:
            views[f"{name}/{pair['id']}"] = pair
    sources: dict[str, list[Source]] = {}
    for item in found:
        name, qid, slot = item["id"].split("/")
        view = views[f"{name}/{qid}"][slot[0]]
        numbered = {source["number"]: source for source in view["sources"]}
        claim = view["claims"][int(slot[1:]) - 1]
        sources[item["id"]] = [
            (numbered[n]["title"], numbered[n]["heading"], numbered[n]["quote"])
            for n in claim["sources"]
        ]
    return sources


def source_key(source: Source) -> str:
    return "\n".join(source)


def extract(
    found: Sequence[Item], sources: Mapping[str, Sequence[Source]], chat: slots.Chat
) -> dict[str, dict[str, list[Slot]]]:
    """The asked slots of every distinct part (one request per question) and the
    stated slots of every distinct source (requests of `BATCH`)."""
    questions: dict[tuple[str, ...], None] = {}
    for item in found:
        questions[tuple(item["parts"])] = None
    asked: dict[str, list[Slot]] = {}
    for parts in questions:
        for part, asks in zip(parts, slots.asked(parts, chat), strict=True):
            asked.setdefault(part, asks)
    distinct = {source_key(s): s for item in found for s in sources[item["id"]]}
    keys = list(distinct)
    stated: dict[str, list[Slot]] = {}
    for start in range(0, len(keys), BATCH):
        batch = keys[start : start + BATCH]
        states = slots.stated([distinct[key] for key in batch], chat)
        stated.update(zip(batch, states, strict=True))
    return {"asked": asked, "stated": stated}


def by_product(
    found: Sequence[Item],
    sources: Mapping[str, Sequence[Source]],
    named: Callable[[str], list[str]],
) -> dict[str, float]:
    """Comparator (a): 0 when the question names products and none of the claim's
    sources belongs to one of them; otherwise 1."""
    scores = {}
    for item in found:
        names = {name for part in item["parts"] for name in named(part)}
        own = {scope.scope_of(title) for title, _, _ in sources[item["id"]]}
        scores[item["id"]] = 0.0 if names and not names & own else 1.0
    return scores


def pairs_of(
    item: Item,
    sources: Sequence[Source],
    extracted: Mapping[str, Mapping[str, list[Slot]]],
) -> list[tuple[str, str]]:
    """Every (asked phrase, stated phrase) pair of one claim."""
    asked = [
        slots.phrase(s) for part in item["parts"] for s in extracted["asked"][part]
    ]
    stated = [
        slots.phrase(s)
        for source in sources
        for s in extracted["stated"][source_key(source)]
    ]
    return [(a, b) for a in asked for b in stated]


def by_pairs(
    found: Sequence[Item],
    sources: Mapping[str, Sequence[Source]],
    extracted: Mapping[str, Mapping[str, list[Slot]]],
    score: PairScore,
) -> dict[str, float]:
    """Comparators (b) and (c): a claim's score is its best pair's."""
    return {
        item["id"]: max(score(pairs_of(item, sources[item["id"]], extracted)))
        for item in found
    }


def reranker_pairs(rerank: Callable[[str, list[str]], list[float]]) -> PairScore:
    """(b): each asked phrase as the query, the stated phrases as documents."""

    def score(pairs: list[tuple[str, str]]) -> list[float]:
        found = []
        for query in dict.fromkeys(a for a, _ in pairs):
            documents = [b for a, b in pairs if a == query]
            found += rerank(query, documents)
        return found

    return score


def judge_schema(count: int) -> dict[str, Any]:
    answers = {"type": "array", "items": {"enum": ["yes", "no"]}}
    return {
        "type": "object",
        "properties": {"answers": answers | {"minItems": count, "maxItems": count}},
        "required": ["answers"],
        "additionalProperties": False,
    }


def yes_probabilities(generated: Sequence[Mapping[str, Any]]) -> list[float]:
    """The probability of "yes" at each position where the reply says yes or no,
    from the two words' log-probabilities among that position's candidates."""
    found = []
    for position in generated:
        if position["token"].strip(STRIP) not in ("yes", "no"):
            continue
        weights = {"yes": -math.inf, "no": -math.inf}
        for candidate in position["top_logprobs"]:
            word = candidate["token"].strip(STRIP)
            if word in weights:
                weights[word] = max(weights[word], candidate["logprob"])
        yes, no = math.exp(weights["yes"]), math.exp(weights["no"])
        found.append(yes / (yes + no))
    return found


def judge_pairs(post: Callable[..., Any]) -> PairScore:
    """(c): the generator judges every pair of one claim in one request; the scores
    are its probabilities of "yes"."""

    def score(pairs: list[tuple[str, str]]) -> list[float]:
        lines = [f"{n}. A: {a}\n   B: {b}" for n, (a, b) in enumerate(pairs, 1)]
        payload = llm.chat_payload(
            JUDGE_PROMPT, "\n".join(lines), judge_schema(len(pairs))
        )
        payload.update(cache_prompt=False, logprobs=True, top_logprobs=5)
        response = post(config.CHAT_URL, json=payload, headers=llm.auth(), timeout=600)
        response.raise_for_status()
        generated = response.json()["choices"][0]["logprobs"]["content"]
        found = yes_probabilities(generated)
        if len(found) != len(pairs):
            raise llm.ModelServerError("the judge's reply does not match its pairs")
        return found

    return score


def gated(
    product: Mapping[str, float], phrase: Mapping[str, float]
) -> dict[str, float]:
    """Comparator (d): a claim failing the product check scores below every other."""
    floor = min(phrase.values(), default=0.0) - 1.0
    return {key: phrase[key] if product[key] else floor for key in phrase}

"""E7 S3: an in-domain near-miss set, labelled by construction.

From an index version's passages the generator writes, for each passage it alone sees,
questions the passage answers (with the answering quote) and near-miss questions on the
same subject it does not answer (with the quote a careless reader would take as the
answer), as SQuAD 2.0 wrote its unanswerable questions against their paragraphs. A
second model reads each question with its passage and must agree with its label, else
the question is dropped. The set measures; it trains nothing.

Items take the claim benchmark's form (`evaluation.claims`), so its scorer and the slot
comparators (`evaluation.slotbench`) apply unchanged: a passage is a case, an answerable
question's quote is a "correct" claim, a near-miss question's quote an "off_question"
one.
"""

import json
import random
from collections.abc import Callable, Sequence
from typing import Any

from limespec import answer, lists, llm, verify
from limespec.models import Passage

Item = dict[str, Any]
Send = Callable[[dict[str, Any]], dict[str, Any]]  # a chat request body to its reply
SHORTEST = 200  # characters: shorter passages rarely hold two questions' worth
KINDS = ("product page", "data sheet", "safety data sheet", "guide or article")

WRITE_PROMPT = """\
You write test questions for a question-answering assistant about Lime Green building \
products. You are given one passage from a Lime Green document. Write:
- "answerable": two questions a customer might ask that this passage answers, each \
with the quote, copied word for word from the passage, that answers it;
- "near_miss": two questions about the same product or subject and topic that this \
passage does NOT answer, though a careless reader might think it does, each with the \
quote, copied word for word from the passage, that such a reader would wrongly take as \
the answer.
Each question must stand alone: name the product or subject. Quotes must be one \
continuous piece of the passage."""

CHECK_PROMPT = """\
You are given a passage from a Lime Green document and a question. Answer "yes" if the \
passage states the answer to the question, "no" if it does not. Judge only from the \
passage."""


def kind_of(passage: Passage) -> str:
    """The passage's kind of document, for the stratified sample."""
    if passage.url.lower().endswith(".pdf"):
        return "safety data sheet" if "SDS" in passage.title else "data sheet"
    return "product page" if "/products/" in passage.url else "guide or article"


def sample(passages: Sequence[Passage], count: int, seed: int) -> list[Passage]:
    """`count` passages, as equal a share of each kind as the kinds allow, drawn with
    `seed`; compiled product lists and short passages left out."""
    rng = random.Random(seed)
    by_kind: dict[str, list[Passage]] = {kind: [] for kind in KINDS}
    for passage in passages:
        if passage.heading != lists.HEADING and len(passage.text) >= SHORTEST:
            by_kind[kind_of(passage)].append(passage)
    for group in by_kind.values():
        rng.shuffle(group)
    taken: list[Passage] = []
    while len(taken) < count and any(by_kind.values()):
        for kind in KINDS:
            if by_kind[kind] and len(taken) < count:
                taken.append(by_kind[kind].pop())
    return taken


def write_schema() -> dict[str, Any]:
    pair = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1},
        },
        "required": ["question", "quote"],
        "additionalProperties": False,
    }
    two = {"type": "array", "items": pair, "minItems": 2, "maxItems": 2}
    return {
        "type": "object",
        "properties": {"answerable": two, "near_miss": two},
        "required": ["answerable", "near_miss"],
        "additionalProperties": False,
    }


def written(passage: Passage, chat: answer.Chat) -> list[Item]:
    """One passage's questions as items; a question whose quote is not in the passage
    is dropped."""
    user = f"Document: {passage.title} › {passage.heading}\nPassage:\n{passage.text}"
    output = chat(WRITE_PROMPT, user, write_schema())
    if not isinstance(output, dict):
        raise llm.ModelServerError("the writer's reply does not match its schema")
    found = []
    for kind, label in (("answerable", "correct"), ("near_miss", "off_question")):
        for number, pair in enumerate(output[kind], 1):
            quote = verify.find_quote(pair["quote"], passage.text)
            if quote is None:
                continue
            found.append(
                {
                    "id": f"p{passage.id}/{kind[0]}{number}",
                    "case": f"p{passage.id}",
                    "parts": [pair["question"].strip()],
                    "claim": quote,
                    "quotes": [quote],
                    "sources": [[passage.title, passage.heading, quote]],
                    "label": label,
                    "kind": kind_of(passage),
                }
            )
    return found


def check_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"answer": {"enum": ["yes", "no"]}},
        "required": ["answer"],
        "additionalProperties": False,
    }


def checked(
    found: Sequence[Item], passages: dict[str, Passage], send: Send
) -> list[Item]:
    """The items a second model agrees with: it reads each question with its passage
    alone and must say the passage answers it exactly when the label says so."""
    kept = []
    for item in found:
        passage = passages[item["case"]]
        user = (
            f"Document: {passage.title} › {passage.heading}\nPassage:\n{passage.text}"
            f"\n\nQuestion: {item['parts'][0]}"
        )
        reply = send(llm.chat_payload(CHECK_PROMPT, user, check_schema()))
        said = json.loads(reply["choices"][0]["message"]["content"])["answer"]
        if (said == "yes") == (item["label"] == "correct"):
            kept.append(item)
    return kept


def shown_claims(
    found: Sequence[Item], passages: dict[str, Passage], send: Send
) -> dict[str, dict[str, int]]:
    """S4 and E8 G1: the claims the answer request, given only the item's passage,
    would show for its question after verification (a near-miss question's claims are
    substitutions), and how many drafted claims verification removed."""
    shown = {}
    for item in found:
        sources = {"S1": passages[item["case"]]}
        body = llm.chat_payload(
            answer.ANSWER_PROMPT,
            answer.user_prompt(item["parts"], sources),
            answer.answer_schema(["S1"], 1),
        )
        reply = send(body)
        output = json.loads(reply["choices"][0]["message"]["content"])
        claims, removed = verify.verify(answer.read_output(output, ["S1"], 1), sources)
        shown[item["id"]] = {"shown": len(claims), "removed": len(removed)}
    return shown

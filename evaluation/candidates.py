"""E8 G0: does a candidate generator, served at some address, do the assistant's two
requests at all?

Five questions go through the first request (its schema: whether an exposure is
described, and the search questions); five near-miss items go through the answer
request (its schema, with the item's passage as the only source), twice, and the two
replies must be identical (greedy decoding). A reply that is not valid JSON of the
schema, or that the server cuts off, fails.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

from limespec import answer, llm
from limespec.models import Passage

Send = Callable[[dict[str, Any]], dict[str, Any]]  # a chat request body to its reply
COUNT = 5


def content(reply: dict[str, Any]) -> str:
    """A finished reply's text; an unfinished one is an error."""
    choice = reply["choices"][0]
    if choice["finish_reason"] != "stop":
        raise llm.ModelServerError(
            f"the reply did not finish ({choice['finish_reason']})"
        )
    return str(choice["message"]["content"])


def first_request_ok(question: str, send: Send) -> bool:
    body = llm.chat_payload(
        answer.UNDERSTAND_PROMPT, f"Question: {question}", answer.UNDERSTAND_SCHEMA
    )
    try:
        answer.read_understanding(json.loads(content(send(body))))
    except (llm.ModelServerError, ValueError, KeyError, TypeError):
        return False
    return True


def answer_text(item: dict[str, Any], passage: Passage, send: Send) -> str | None:
    """The answer request's reply for one item, or None when it breaks the schema."""
    sources = {"S1": passage}
    body = llm.chat_payload(
        answer.ANSWER_PROMPT,
        answer.user_prompt(item["parts"], sources),
        answer.answer_schema(["S1"], 1),
    )
    try:
        text = content(send(body))
        answer.read_output(json.loads(text), ["S1"], 1)
    except (llm.ModelServerError, ValueError, KeyError, TypeError):
        return None
    return text


def smoke(
    questions: Sequence[str],
    found: Sequence[dict[str, Any]],
    passages: dict[str, Passage],
    send: Send,
) -> dict[str, Any]:
    """G0's three counts, each out of `COUNT`, and whether the candidate passes."""
    first = sum(first_request_ok(q, send) for q in questions[:COUNT])
    replies = [answer_text(i, passages[i["case"]], send) for i in found[:COUNT]]
    again = [answer_text(i, passages[i["case"]], send) for i in found[:COUNT]]
    valid = sum(reply is not None for reply in replies)
    same = sum(a is not None and a == b for a, b in zip(replies, again, strict=True))
    return {
        "first_request": first,
        "answers": valid,
        "repeated": same,
        "passes": first == valid == same == COUNT,
    }

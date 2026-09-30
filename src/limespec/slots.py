"""Slots: what a question's parts ask for, and what a quote states (E7).

A slot is a subject and a property: "Lime Green's production plant" and "year it was
built". A claim answers a part only if one of its quotes states the property the part
asks for, of the same subject. Each side is read alone by the generator: the asked slots
from the question's parts with no evidence, the stated slots from each quote and its
document's title with no question, so neither is bent to fit the other.
"""

from collections.abc import Callable, Sequence
from typing import Any

from limespec.llm import ModelServerError

Chat = Callable[[str, str, dict[str, Any]], object]  # system, user, schema → JSON
Slot = dict[str, str]  # {"subject": ..., "property": ...}
Source = tuple[str, str, str]  # a quote's document title, heading, and the quote
MAX_SLOTS = 4  # slots read from one part or one quote

ASKED_PROMPT = """\
You read customer questions about Lime Green building products. For each numbered \
question, list what it asks for as slots. A slot is a subject and a property:
- subject: the product, material, document or thing the question is about, in the \
question's own words;
- property: the kind of information wanted about that subject, as a short noun phrase \
(such as "drying time", "fire classification", "backgrounds it suits", "list of \
products for internal walls").
A question asking two things gives two slots. Do not answer the questions."""

STATED_PROMPT = """\
You read short quotes from Lime Green documents. For each numbered quote, list what it \
states as slots. A slot is a subject and a property:
- subject: the product, material, document or thing the statement is about, named as \
the quote or its document names it;
- property: the kind of information the quote gives about that subject, as a short \
noun phrase, not the information itself (such as "drying time", "fire \
classification", "one of the backgrounds it suits").
A quote stating two things gives two slots. Describe only what the quote itself says."""


def slots_schema(count: int) -> dict[str, Any]:
    """The reply: for each of `count` numbered texts, its slots."""
    slot = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "minLength": 1},
            "property": {"type": "string", "minLength": 1},
        },
        "required": ["subject", "property"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "slots": {
                "type": "array",
                "items": slot,
                "minItems": 1,
                "maxItems": MAX_SLOTS,
            }
        },
        "required": ["slots"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": item,
                "minItems": count,
                "maxItems": count,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def read_slots(output: object, count: int) -> list[list[Slot]]:
    """The reply checked again against its schema: `count` lists of slots."""
    items = output.get("items") if isinstance(output, dict) else None
    if not isinstance(items, list) or len(items) != count:
        raise ModelServerError("the model's slots do not match their schema")
    found = []
    for item in items:
        slots = item.get("slots") if isinstance(item, dict) else None
        if not isinstance(slots, list) or not 1 <= len(slots) <= MAX_SLOTS:
            raise ModelServerError("the model's slots do not match their schema")
        read = []
        for slot in slots:
            if not isinstance(slot, dict) or set(slot) != {"subject", "property"}:
                raise ModelServerError("the model's slots do not match their schema")
            read.append(
                {key: str(slot[key]).strip() for key in ("subject", "property")}
            )
        found.append(read)
    return found


def asked(parts: Sequence[str], chat: Chat) -> list[list[Slot]]:
    """The slots each part of one question asks for, read with no evidence."""
    lines = [f"{number}. {part}" for number, part in enumerate(parts, 1)]
    output = chat(ASKED_PROMPT, "\n".join(lines), slots_schema(len(parts)))
    return read_slots(output, len(parts))


def stated(sources: Sequence[Source], chat: Chat) -> list[list[Slot]]:
    """The slots each quote states, read with its document's title and no question."""
    lines = []
    for number, (title, heading, quote) in enumerate(sources, 1):
        where = f"{title} › {heading}" if heading and heading != title else title
        lines.append(f"{number}. Document: {where}\n   Quote: {quote}")
    output = chat(STATED_PROMPT, "\n".join(lines), slots_schema(len(sources)))
    return read_slots(output, len(sources))


def phrase(slot: Slot) -> str:
    """A slot as one short phrase: "Solo plaster: drying time"."""
    return f"{slot['subject']}: {slot['property']}"

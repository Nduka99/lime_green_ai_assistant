"""What a question's parts ask for and what a quote states (E7). Invented texts; the
model is a stand-in."""

from typing import Any

import pytest

from limespec import slots
from limespec.llm import ModelServerError


def reply(*items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "items": [
            {"slots": [{"subject": s, "property": p} for s, p in item]}
            for item in items
        ]
    }


def test_asked_slots_are_read_from_the_parts_alone() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        seen.append((system, user, schema))
        return reply(
            [("Solo", "drying time")], [("Duro", "cost"), ("Duro", "coverage")]
        )

    found = slots.asked(
        ["How long does Solo take to dry?", "Duro cost and coverage?"], chat
    )

    assert found[1] == [
        {"subject": "Duro", "property": "cost"},
        {"subject": "Duro", "property": "coverage"},
    ]
    system, user, schema = seen[0]
    assert system == slots.ASKED_PROMPT
    assert user == "1. How long does Solo take to dry?\n2. Duro cost and coverage?"
    assert schema["properties"]["items"]["minItems"] == 2


def test_stated_slots_are_read_from_each_quote_and_its_document_only() -> None:
    seen: list[str] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        seen.append(user)
        return reply([("Solo", "drying time")], [("Duro", "fire classification")])

    found = slots.stated(
        [("Solo", "Solo", "Dries in 2 days."), ("Duro — Data", "Fire", "Class A1.")],
        chat,
    )

    assert found[0] == [{"subject": "Solo", "property": "drying time"}]
    assert seen[0] == (
        "1. Document: Solo\n   Quote: Dries in 2 days.\n"
        "2. Document: Duro — Data › Fire\n   Quote: Class A1."
    )


@pytest.mark.parametrize(
    "output",
    [
        None,
        {"items": []},
        {"items": [{"slots": []}]},
        {"items": [{"slots": [{"subject": "Solo"}]}]},
        {"items": ["Solo"]},
    ],
)
def test_a_reply_that_breaks_the_schema_is_an_error(output: object) -> None:
    with pytest.raises(ModelServerError, match="do not match their schema"):
        slots.read_slots(output, 1)


def test_a_slot_reads_as_subject_then_kind_of_information() -> None:
    assert slots.phrase({"subject": "Solo", "property": "drying time"}) == (
        "Solo: drying time"
    )

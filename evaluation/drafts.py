"""The claims the answer request drafts, with their quotes, before verification (E5).

`verify` removes a draft claim whole and the audit record keeps only its text and the
reason, not the quotes it cited. A change to verification can only be judged on the
drafts themselves, so they are written again: for an audit record's question and the
passages its model was given, the first request and the answer request run as the
assistant runs them, and every draft is kept with the current checks' verdict.

The removed drafts are then labelled by reading, before any rule is scored:
"wrong" (wrongly removed: the passages given state the claim) or "right". A
candidate rule is scored by checking every labelled draft again with the code as it
stands (`rescore`): it should restore the wrongly removed and none of the rightly
removed.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from limespec import answer
from limespec.models import DraftClaim, DraftEvidence, Passage, Rejection
from limespec.verify import check_claim

Item = dict[str, Any]
LABELS = ("wrong", "right")  # wrongly or rightly removed


def sources_of(passages: Sequence[Passage]) -> dict[str, Passage]:
    """The passages under the ids the answer request gives them: S1, S2, ..."""
    return {f"S{number}": passage for number, passage in enumerate(passages, 1)}


def draft_row(draft: DraftClaim, sources: Mapping[str, Passage]) -> dict[str, Any]:
    """One draft as plain data, with the reason the current checks remove it ("" when
    they keep it)."""
    checked = check_claim(draft, sources)
    return {
        "text": draft.text,
        "part": draft.part,
        "evidence": [
            {"source_id": e.source_id, "quote": e.quote} for e in draft.evidence
        ],
        "removed": checked.reason if isinstance(checked, Rejection) else "",
    }


def drafted(question: str, passages: Sequence[Passage], chat: answer.Chat) -> Item:
    """The question's parts and every claim the answer request drafts from these
    passages. An emergency, or a question given no passages, drafts nothing."""
    exposed, parts = answer.understand(question, chat)
    if exposed or not passages:
        return {"parts": [], "drafts": []}
    sources = sources_of(passages)
    output = chat(
        answer.ANSWER_PROMPT,
        answer.user_prompt(parts, sources),
        answer.answer_schema(list(sources), len(parts)),
    )
    drafts = answer.read_output(output, list(sources), len(parts))
    return {"parts": parts, "drafts": [draft_row(draft, sources) for draft in drafts]}


def removed(items: Sequence[Item]) -> list[str]:
    """The ids of the removed drafts, "<item id>/<draft number>": what is labelled."""
    return [
        f"{item['id']}/{number}"
        for item in items
        for number, draft in enumerate(item["drafts"], 1)
        if draft["removed"]
    ]


def rescore(
    items: Sequence[Item],
    labels: Mapping[str, str],
    passages: Mapping[int, Passage],
) -> dict[str, Any]:
    """Every labelled draft checked again with the checks as they stand: how many of
    the wrongly removed are now kept, and which rightly removed ones are (the rule
    allows none)."""
    found: dict[str, Any] = {label: {"of": 0, "kept": []} for label in LABELS}
    for item in items:
        sources = sources_of([passages[passage_id] for passage_id in item["passages"]])
        for number, row in enumerate(item["drafts"], 1):
            label = labels.get(f"{item['id']}/{number}")
            if label is None:
                continue
            evidence = tuple(
                DraftEvidence(e["source_id"], e["quote"]) for e in row["evidence"]
            )
            draft = DraftClaim(row["text"], evidence, row["part"])
            found[label]["of"] += 1
            if not isinstance(check_claim(draft, sources), Rejection):
                found[label]["kept"].append(f"{item['id']}/{number}")
    return found

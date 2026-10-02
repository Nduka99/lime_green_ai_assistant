"""Replay the answer path up to the answer request: the first request and the searches,
with no answer generated (E5).

A retrieval change is judged by whether each keyed part's evidence reaches the model
(`evaluation.reach`). Generating and grading answers to find that out takes hours; the
searches alone take minutes, and they are the same code the assistant runs
(`answer.understand`, `answer.gather`). The search questions the first request wrote
can be kept from an earlier replay, so two retrieval arms differ in nothing else.
"""

import time
from collections.abc import Callable
from typing import Any

from evaluation import grades
from limespec import answer
from limespec.models import Part, Passage

# The first request: whether the question describes an exposure, and its search
# questions with their items.
Understand = Callable[[str], tuple[bool, list[Part]]]


def replay(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    understand: Understand,
    retrieve: answer.Retrieve,
    parts: dict[str, list[Part]] | None = None,
    scoped: answer.Retrieve | None = None,
    extra: answer.Extra | None = None,
    items: bool = False,
) -> tuple[dict[str, list[Part]], dict[str, list[Passage]], dict[str, float]]:
    """For each question the key expects answered: its search questions (from
    `parts` when an earlier replay wrote them, else from the first request), the
    passages the answer request would be given, and the seconds its searches took.
    With `items`, each part's items are searched too (X48). A question read as an
    emergency has no search questions and is given nothing."""
    cases = grades.cases_by_question(key, questions)
    written: dict[str, list[Part]] = {}
    given: dict[str, list[Passage]] = {}
    seconds: dict[str, float] = {}
    for row in questions:
        if "answered" not in grades.expected_statuses(cases[row["id"]][0]):
            continue
        if parts is not None and row["id"] in parts:
            searches = parts[row["id"]]
        else:
            exposed, searches = understand(row["question"])
            searches = [] if exposed else searches
        written[row["id"]] = searches
        started = time.perf_counter()
        found: tuple[Passage, ...] = ()
        if searches:
            listed = answer.items_to_search(searches) if items else []
            asked = [part.question for part in searches]
            found = answer.gather(asked, retrieve, scoped, extra, listed)
        seconds[row["id"]] = time.perf_counter() - started
        given[row["id"]] = list(found)
    return written, given, seconds


def saved_parts(
    written: dict[str, list[Part]],
) -> tuple[dict[str, list[str]], dict[str, list[list[str]]]]:
    """Search questions and their items as JSON: two maps by question id, so a reader
    of the search questions alone reads them as before X48."""
    asked = {qid: [part.question for part in found] for qid, found in written.items()}
    items = {
        qid: [list(part.items) for part in found] for qid, found in written.items()
    }
    return asked, items


def read_parts(saved: dict[str, Any]) -> dict[str, list[Part]]:
    """An earlier replay's search questions with their items (none in a file written
    before X48)."""
    items = saved.get("items", {})
    found = {}
    for qid, asked in saved["parts"].items():
        listed = items.get(qid, [[] for _ in asked])
        found[qid] = [Part(q, tuple(i)) for q, i in zip(asked, listed, strict=True)]
    return found

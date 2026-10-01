"""Replay the answer path up to the answer request: the first request and the searches,
with no answer generated (E5).

A retrieval change is judged by whether each keyed part's evidence reaches the model
(`evaluation.reach`). Generating and grading answers to find that out takes hours; the
searches alone take minutes, and they are the same code the assistant runs
(`answer.understand`, `answer.gather`). The search questions the first request wrote
can be kept from an earlier replay, so two retrieval arms differ in nothing else.
"""

from collections.abc import Callable
from typing import Any

from evaluation import grades
from limespec import answer
from limespec.models import Passage

# The first request: whether the question describes an exposure, and its search
# questions.
Understand = Callable[[str], tuple[bool, list[str]]]


def replay(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    understand: Understand,
    retrieve: answer.Retrieve,
    parts: dict[str, list[str]] | None = None,
    scoped: answer.Retrieve | None = None,
    extra: answer.Extra | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[Passage]]]:
    """For each question the key expects answered: its search questions (from
    `parts` when an earlier replay wrote them, else from the first request) and the
    passages the answer request would be given. A question read as an emergency has
    no search questions and is given nothing."""
    cases = grades.cases_by_question(key, questions)
    written: dict[str, list[str]] = {}
    given: dict[str, list[Passage]] = {}
    for row in questions:
        if "answered" not in grades.expected_statuses(cases[row["id"]][0]):
            continue
        if parts is not None and row["id"] in parts:
            searches = parts[row["id"]]
        else:
            exposed, searches = understand(row["question"])
            searches = [] if exposed else searches
        written[row["id"]] = searches
        found = answer.gather(searches, retrieve, scoped, extra) if searches else ()
        given[row["id"]] = list(found)
    return written, given

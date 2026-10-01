"""Evidence reach: did the passages an answer's model was given hold the key's evidence?

Every answer's audit record keeps the ids of the passages its model saw, so reach is
measured from what actually reached the model in any arm, a search per part included,
without repeating the search. A part is reached when each of its evidence quotes is
found in some given passage by the matcher claims are verified with (`find_quote`),
and each picture it cites as what it shows (held-out v6) is a given passage's
picture. The ceiling says whether the index version holds them at all.
"""

from collections.abc import Collection, Sequence
from typing import Any

from evaluation import grades
from limespec.models import Passage
from limespec.verify import find_quote

# Evidence matched as quotes: a page's, PDF's or Word file's text, and a picture's
# own words (X43). A picture cited as what it shows is matched by its id.
TEXT_EVIDENCE = {"page_text", "pdf_text", "docx_text", "image_text"}
VISUAL = "image_visual"
# Joins a version's passages into one text that no quote can match across: a quote
# pattern allows only whitespace and cell marks between its words.
BOUNDARY = "\n\x00\n"


def part_evidence(case: dict[str, Any]) -> list[tuple[str, list[str], list[str]]]:
    """Each part of a case with evidence to reach, as (part id, its quotes, the
    pictures it cites as what they show)."""
    found = []
    for number, part in enumerate(case.get("parts", []), 1):
        quotes, pictures = [], []
        for evidence in part.get("evidence", []):
            kind = evidence.get("kind", "page_text")
            if kind in TEXT_EVIDENCE:
                quotes.append(evidence["quote"])
            elif kind == VISUAL:
                pictures.append(evidence["image"])
        if quotes or pictures:
            found.append((part.get("id", f"p{number}"), quotes, pictures))
    return found


def part_quotes(case: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Each part of a case that has text evidence, as (part id, its quotes)."""
    return [(part, quotes) for part, quotes, _ in part_evidence(case) if quotes]


def holds(texts: Sequence[str], quotes: Sequence[str]) -> bool:
    """Whether every quote is found in one of the texts."""
    return all(any(find_quote(quote, text) for text in texts) for quote in quotes)


def score(
    key: dict[str, Any],
    questions: list[dict[str, str]],
    given: dict[str, list[Passage]],
    version_texts: Sequence[str],
    version_pictures: Collection[str] = (),
) -> list[dict[str, Any]]:
    """One row per keyed part of every question the key expects answered: whether the
    passages given for that question (`given`, by question id) hold its evidence, and
    whether the version does (`version_texts`, its searchable passages, and
    `version_pictures`, the pictures they were made from)."""
    cases = grades.cases_by_question(key, questions)
    everything = BOUNDARY.join(version_texts)
    rows = []
    for row in questions:
        case = cases[row["id"]][0]
        if "answered" not in grades.expected_statuses(case):
            continue
        texts = [passage.text for passage in given.get(row["id"], [])]
        seen = {passage.image for passage in given.get(row["id"], [])}
        for part_id, quotes, pictures in part_evidence(case):
            rows.append({
                "id": row["id"],
                "case": case["id"],
                "part": part_id,
                "reached": holds(texts, quotes) and set(pictures) <= seen,
                "ceiling": holds([everything], quotes)
                and set(pictures) <= set(version_pictures),
            })  # fmt: skip
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Parts reached and in the version, and questions with every part reached."""
    by_question: dict[str, list[bool]] = {}
    for row in rows:
        by_question.setdefault(row["id"], []).append(row["reached"])
    return {
        "parts": len(rows),
        "reached": sum(row["reached"] for row in rows),
        "ceiling": sum(row["ceiling"] for row in rows),
        "questions": len(by_question),
        "every_part": sum(all(parts) for parts in by_question.values()),
    }


def text(found: dict[str, Any]) -> str:
    parts = found["parts"] or 1  # an empty key reports 0 of 0
    return (
        f"parts reached {found['reached']}/{found['parts']} "
        f"({found['reached'] / parts:.3f}); in the version {found['ceiling']}/"
        f"{found['parts']} ({found['ceiling'] / parts:.3f}); questions with every "
        f"part reached {found['every_part']}/{found['questions']}"
    )

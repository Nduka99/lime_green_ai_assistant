"""Which questions the first request marks as asking what a picture shows (E10).

Pictures are read for their words only, so the answer path removes any claim for a
part so marked. This measures the marking on sets the change was not derived from:
questions about what a picture shows should be marked, and text questions should not.
"""

from collections.abc import Callable, Sequence
from typing import Any

from limespec.models import Part


def read(
    questions: Sequence[dict[str, Any]], understand: Callable[[str], Sequence[Part]]
) -> dict[str, Any]:
    """Each question's parts with their marks, and the ids of the questions that
    have a marked part."""
    parts = {
        row["id"]: [
            {"question": part.question, "pictured": part.pictured}
            for part in understand(row["question"])
        ]
        for row in questions
    }
    marked = [qid for qid, found in parts.items() if any(p["pictured"] for p in found)]
    return {"questions": len(parts), "marked": marked, "parts": parts}

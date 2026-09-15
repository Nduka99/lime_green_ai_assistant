"""What a reader sees for one answer, as plain data shared by every interface.

The command line prints it, the web page renders it and `/api/answer` returns it
as JSON, so all three show the same status, claims and sources. It holds only
verified claims, their numbered citations, the fixed notice and, for a refusal,
the closest pages. Claims removed by verification are never shown.
"""

from typing import TypedDict

from limespec.answer import closest_pages
from limespec.models import Answer


class Source(TypedDict):
    """One verified quote, numbered so claims can point to it."""

    number: int
    title: str
    heading: str
    quote: str
    link: str  # opens the live page at the quote
    url: str
    captured: str  # capture date, YYYY-MM-DD


class ClaimView(TypedDict):
    text: str
    sources: list[int]  # numbers of the sources that support it


class Page(TypedDict):
    title: str
    url: str


class AnswerView(TypedDict):
    question: str
    status: str
    notice: str  # fixed application text, possibly several lines; may be empty
    claims: list[ClaimView]
    sources: list[Source]
    closest_pages: list[Page]  # only for insufficient evidence


def view(answer: Answer) -> AnswerView:
    """The reader's view of an answer; each distinct quote is one numbered source."""
    sources: list[Source] = []
    numbers: dict[tuple[int, str], int] = {}
    claims: list[ClaimView] = []
    for claim in answer.claims:
        refs: list[int] = []
        for evidence in claim.evidence:
            key = (evidence.passage_id, evidence.quote)
            if key not in numbers:
                numbers[key] = len(sources) + 1
                sources.append(
                    Source(
                        number=numbers[key],
                        title=evidence.title,
                        heading=evidence.heading,
                        quote=" ".join(evidence.quote.split()),
                        link=evidence.link,
                        url=evidence.url,
                        captured=evidence.fetched_at[:10],
                    )
                )
            if numbers[key] not in refs:
                refs.append(numbers[key])
        claims.append(ClaimView(text=claim.text, sources=refs))
    closest = (
        [Page(title=p.title, url=p.url) for p in closest_pages(answer.passages)]
        if answer.status == "insufficient_evidence"
        else []
    )
    return AnswerView(
        question=answer.question,
        status=answer.status,
        notice=answer.notice,
        claims=claims,
        sources=sources,
        closest_pages=closest,
    )

"""Plain data records passed between the modules."""

from dataclasses import dataclass
from typing import Literal

# The only three outcomes of a question. An unreachable model or a damaged index
# is an operational error, not a status.
Status = Literal["answered", "insufficient_evidence", "safety_referral"]


@dataclass(frozen=True)
class Passage:
    """One section of one web page: the unit that is searched and cited."""

    id: int
    url: str
    title: str  # page title
    heading: str  # section heading; the passage text starts with it
    text: str
    fetched_at: str  # when the page was captured, ISO 8601 UTC


@dataclass(frozen=True)
class DraftEvidence:
    """A quote as the model returned it, before verification."""

    source_id: str  # "S1", "S2", ...: the passage's position in the prompt
    quote: str


@dataclass(frozen=True)
class DraftClaim:
    """A claim as the model returned it, before verification."""

    text: str
    evidence: tuple[DraftEvidence, ...]


@dataclass(frozen=True)
class DraftAnswer:
    """The answer request's reply, after its shape is checked, before verification."""

    claims: tuple[DraftClaim, ...]
    answers_every_part: bool


@dataclass(frozen=True)
class Evidence:
    """A verified quote and the stored details needed to cite it.

    Nothing here is written by the model: the quote is the passage's own wording
    and the rest comes from the index.
    """

    passage_id: int
    url: str
    title: str
    heading: str
    quote: str
    link: str  # opens the live page with the quote highlighted
    fetched_at: str


@dataclass(frozen=True)
class Claim:
    """A claim that passed verification, shown with its evidence."""

    text: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Rejection:
    """A claim removed by verification: kept for evaluation, never shown as fact."""

    text: str
    reason: str


@dataclass(frozen=True)
class Answer:
    """Core answer plus audit data; interfaces must never render `rejected`."""

    question: str
    status: Status
    notice: str  # fixed application text; empty when the claims need no caution
    claims: tuple[Claim, ...]
    passages: tuple[Passage, ...]  # the passages the model was given, best first
    rejected: tuple[Rejection, ...]

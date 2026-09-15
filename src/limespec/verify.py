"""Check each claim the model returned against the passages it cites.

A claim is shown only if every check passes:

1. it has at least one quote, and every source id names a supplied passage;
2. every quote appears in its passage, ignoring only case and whitespace;
3. every number in the claim, with its sign, appears in one of its quotes;
4. every regulation the claim mentions (Building Regulations, Part L, building
   control ...) is mentioned in its quotes.

These are evidence checks: none of them tries to judge what a sentence means,
so they apply equally to any wording. Checks 3 and 4 stop a claim adding a
figure or a regulation that its evidence does not contain, which is how an
unsupported compliance verdict would be built. Whether a claim is a verdict or a
diagnosis is left to the prompt and was checked when the answers were graded.

A failing claim is removed whole and recorded with its reason; nothing is
repaired or regenerated.
"""

import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote as percent_encode

from limespec.models import Claim, DraftClaim, Evidence, Passage, Rejection

# A sign belongs to a number only where it cannot be a range dash: "-5 °C" has a
# sign, "3-6 mm" is a range. Unicode minus and en dash are read as a minus.
NUMBER = re.compile(r"(?<![\w.])[-+−–]?[0-9]+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?")

# Names of rules and approvals, each counted under one name so that "complies"
# in a claim is matched by "comply" in its quote. Specific names also match the
# generic term: this stops "Building Regulations" being supported by a quote
# that mentions unrelated environmental regulations.
REGULATION_TERMS = {
    "building regulations": r"\bbuilding\s+reg(?:ulation)?s?\b",
    "regulations": r"\bregulations?\b|\bregs\b",
    "building control": r"\bbuilding\s+control\b",
    "approved document": r"\bapproved\s+documents?\b",
    "planning permission": r"\bplanning\s+permission\b",
    "listed building consent": r"\blisted\s+building\s+consent\b",
    "approval": r"\bapprov(?:e|es|ed|ing|al|als)\b",
    "compliance": r"\bcompl(?:y|ies|ied|ying|iant|iance)\b",
}
# "Part L" of the Building Regulations, including sub-parts such as "Part L1B".
PART = re.compile(r"\bpart\s+([a-r])(?:[0-9][a-z]?)?\b", re.IGNORECASE)


def find_quote(quote: str, text: str) -> str | None:
    """The passage's own wording of `quote`, or None if the passage does not contain it.

    Only case and whitespace may differ, because a model may re-wrap lines; the
    words must appear in the same order with nothing between them. The quote must
    start and end at word edges, so "3 to 6" cannot match "3 to 60 mm".
    """
    words = quote.split()
    if not words:
        return None
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(word) for word in words) + r"(?!\w)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(0) if match else None


def quote_link(url: str, quote: str) -> str:
    """A link that opens the page with the quote highlighted (a URL text fragment)."""
    text = " ".join(quote.split())
    # Percent-encoding leaves '-' alone, but inside a text fragment it is syntax.
    return f"{url}#:~:text={percent_encode(text, safe='').replace('-', '%2D')}"


def numbers(text: str) -> set[str]:
    """Every number in the text, preserving an explicit plus or minus sign."""
    found = NUMBER.findall(text)
    return {n.replace("−", "-").replace("–", "-") for n in found}


def regulation_terms(text: str) -> set[str]:
    """The rules and approvals the text mentions, each under one name."""
    found = {
        name
        for name, pattern in REGULATION_TERMS.items()
        if re.search(pattern, text, re.IGNORECASE)
    }
    return found | {f"part {letter.lower()}" for letter in PART.findall(text)}


def check_claim(draft: DraftClaim, sources: Mapping[str, Passage]) -> Claim | Rejection:
    """The verified claim with its citations, or the reason it must be removed."""
    if not draft.evidence:
        return Rejection(draft.text, "no quote")
    evidence = []
    for item in draft.evidence:
        passage = sources.get(item.source_id)
        if passage is None:
            return Rejection(draft.text, f"unknown source {item.source_id}")
        quote = find_quote(item.quote, passage.text)
        if quote is None:
            return Rejection(
                draft.text, f"quote not in {item.source_id}: {item.quote!r}"
            )
        evidence.append(
            Evidence(
                passage_id=passage.id,
                url=passage.url,
                title=passage.title,
                heading=passage.heading,
                quote=quote,
                link=quote_link(passage.url, quote),
                fetched_at=passage.fetched_at,
            )
        )
    quoted = " ".join(item.quote for item in evidence)
    missing = sorted(numbers(draft.text) - numbers(quoted))
    if missing:
        return Rejection(draft.text, f"number not in its quotes: {', '.join(missing)}")
    unquoted = sorted(regulation_terms(draft.text) - regulation_terms(quoted))
    if unquoted:
        return Rejection(
            draft.text, f"regulation not in its quotes: {', '.join(unquoted)}"
        )
    return Claim(draft.text, tuple(evidence))


def verify(
    drafts: Sequence[DraftClaim], sources: Mapping[str, Passage]
) -> tuple[tuple[Claim, ...], tuple[Rejection, ...]]:
    """Split the model's claims into those to show and those removed, keeping order."""
    results = [check_claim(draft, sources) for draft in drafts]
    claims = tuple(result for result in results if isinstance(result, Claim))
    rejected = tuple(result for result in results if isinstance(result, Rejection))
    return claims, rejected

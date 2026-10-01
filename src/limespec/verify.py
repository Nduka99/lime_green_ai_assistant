"""Check each claim the model returned against the passages it cites.

A claim is shown only if every check passes:

1. it has at least one quote, and every source id names a supplied passage;
2. every quote appears in its passage, ignoring only case and whitespace; a quote
   the model cited to the wrong passage is cited to the supplied passage holding it;
3. every number in the claim, with its sign, appears in one of its quotes, or, if
   unsigned, in a cited passage's title, heading or text together with the token it
   is part of ("Silic8", "25kg") or the word before it ("ISO 9001");
4. every regulation the claim mentions (Building Regulations, Part L, building
   control ...) is mentioned in its quotes;
5. it states no price, whatever it quotes (the price fence, `prices`).

These are evidence checks: none of them tries to judge what a sentence means,
so they apply equally to any wording. Checks 3 and 4 stop a claim adding a
figure or a regulation that its evidence does not contain, which is how an
unsupported compliance verdict would be built. Whether a claim is a verdict or a
diagnosis is left to the prompt and was checked when the answers were graded.

A failing claim is removed whole and recorded with its reason; nothing is
repaired or regenerated.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from functools import lru_cache
from urllib.parse import quote as percent_encode
from urllib.parse import urlsplit, urlunsplit

from limespec import lists, prices
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
# The gap between two quoted words: whitespace, which may hold the " | " this project
# puts between a table's cells (X9). The mark is not the document's words, so a row
# quoted as the page reads it ("Reaction to fire Class A1") still matches.
WORD_GAP = r"\s+(?:\|\s+)*"
# Where a digit meets a non-digit, or at punctuation, whitespace is optional: Docling
# spaces superscripts that the page and its text layer do not ("N/mm 2").
OPTIONAL_GAP = r"\s*(?:\|\s+)*"
# Typographic forms of one character; the page's curly quotes, which Docling writes
# straight, are the same quote marks.
TYPOGRAPHY = str.maketrans(
    dict.fromkeys("‘’‚′", "'")
    | dict.fromkeys("“”„″", '"')
    | dict.fromkeys("–—−‐‑", "-")
)
# The units a quote is matched by: a number, with its decimal point or comma, is one
# unit ("1.5" never matches "1. 5"); any other character is its own unit.
UNIT = re.compile(r"\d+(?:[.,]\d+)*|\S")


@lru_cache(maxsize=512)  # about 25 MB at most: passages are up to 1,500 characters
def folded(text: str) -> tuple[str, tuple[int, ...]]:
    """The text with typographic and Unicode compatibility forms folded (NFKC: "²"
    as "2", "ﬁ" as "fi"), and each folded character's position in the text.
    Remembered, as the same passages are checked again and again."""
    chars = []
    where = []
    for index, char in enumerate(text):
        form = unicodedata.normalize("NFKC", char.translate(TYPOGRAPHY))
        for piece in form.translate(TYPOGRAPHY):
            chars.append(piece)
            where.append(index)
    return "".join(chars), tuple(where)


def same_kind(before: str, after: str) -> bool:
    """Whether two neighbouring units are letters, or digits, where spacing is
    part of the words ("therapist" is not "the rapist", nor "36" "3 6")."""
    letters = before[-1].isalpha() and after[0].isalpha()
    return letters or (before[-1].isdigit() and after[0].isdigit())


def quote_pattern(quote: str) -> str:
    """The pattern a quote is found by (X9 report, "Follow-up: quote matching")."""
    units = list(UNIT.finditer(folded(quote)[0]))
    # A point or comma between two digits belongs to a number: spacing around it
    # stays as the quote has it ("1, 2" is not "1,2").
    decimal = set()
    for index in range(1, len(units) - 1):
        before, mark, after = (unit.group() for unit in units[index - 1 : index + 2])
        if mark in ".," and before[-1].isdigit() and after[0].isdigit():
            decimal |= {index - 1, index}
    parts = []
    for index, unit in enumerate(units):
        if index:
            previous = units[index - 1]
            spaced = unit.start() > previous.end()
            if index - 1 in decimal or same_kind(previous.group(), unit.group()):
                parts.append(WORD_GAP if spaced else "")
            else:
                parts.append(OPTIONAL_GAP)
        parts.append(re.escape(unit.group()))
    return r"(?<!\w)" + "".join(parts) + r"(?!\w)"


def find_quote(quote: str, text: str) -> str | None:
    """The passage's own wording of `quote`, or None if the passage does not contain it.

    Case, typographic forms and Unicode compatibility forms may differ, and so may
    whitespace where a model re-wraps lines or where a digit meets a non-digit
    (superscripts); between letters, or digits, spacing must be the quote's. The
    table cell mark reads as whitespace. The quote must start and end at word edges,
    so "3 to 6" cannot match "3 to 60 mm".
    """
    if not quote.split():
        return None
    text_folded, where = folded(text)
    match = re.search(quote_pattern(quote), text_folded, re.IGNORECASE)
    if match is None:
        return None
    return text[where[match.start()] : where[match.end() - 1] + 1]


def encoded(url: str) -> str:
    """The address with its path and query percent-encoded (RFC 3986), escapes it
    already has kept: a path with spaces ("carbon footprint - solo.pdf") is cut at
    the first space wherever text is turned into links."""
    parts = urlsplit(url)
    path = percent_encode(parts.path, safe="/%!$&'()*+,;=:@-._~")
    query = percent_encode(parts.query, safe="/?%!$&'()*+,;=:@-._~")
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def directive_text(text: str) -> str:
    """Words for a text directive: percent-encoded, '-' included, as it is syntax."""
    return percent_encode(" ".join(text.split()), safe="").replace("-", "%2D")


def quote_link(url: str, quote: str, page: int | None = None) -> str:
    """A link that opens the page with the quote highlighted (a URL text fragment),
    or a PDF at the quote's page (RFC 8118 `page=`: browsers do not find text
    fragments in PDFs). A text directive matches inside one block of the page, so a
    quote whose wording spans lines of its passage (paragraphs, list items, a heading
    and its text) is linked as a range from its first line to its last."""
    address = encoded(url)
    if page is not None:
        return f"{address}#page={page}"
    lines = [line for line in quote.split("\n") if line.strip()]
    if len(lines) > 1:
        start, end = directive_text(lines[0]), directive_text(lines[-1])
        return f"{address}#:~:text={start},{end}"
    return f"{address}#:~:text={directive_text(quote)}"


def source_link(passage: Passage, quote: str) -> str:
    """Where a citation opens: the quote highlighted on its page, except for a compiled
    product list, whose sentence is not on the page, so the page opens as it is."""
    if passage.heading == lists.HEADING:
        return passage.url
    return quote_link(passage.url, quote, passage.page)


def numbers(text: str) -> set[str]:
    """Every number in the text, preserving an explicit plus or minus sign."""
    found = NUMBER.findall(text)
    return {n.replace("−", "-").replace("–", "-") for n in found}


def number_units(claim: str, number: str) -> list[str]:
    """What an unsigned number in a claim is found with in a passage: each token it is
    part of ("Silic8", "25kg"), or, where it stands alone, the word before it and the
    number ("ISO 9001"). A signed number has none: only its quotes can support it."""
    if not number[0].isdigit():
        return []
    units = []
    for match in re.finditer(rf"(?<![\d.]){re.escape(number)}(?!\.?\d)", claim):
        start, end = match.span()
        while start > 0 and claim[start - 1].isalnum():
            start -= 1
        while end < len(claim) and claim[end].isalnum():
            end += 1
        if (start, end) != match.span():
            units.append(claim[start:end])
            continue
        before = re.search(r"(\w+)\W*$", claim[:start])
        if before:
            units.append(claim[before.start(1) : end])
    return units


def named_number(claim: str, number: str, passages: Sequence[Passage]) -> bool:
    """Whether a cited passage states the number as the claim uses it (check 3):
    digits inside names ("Silic8", "ISO 9001") are rarely in the quoted words."""
    places = [f"{p.title}\n{p.heading}\n{p.text}" for p in passages]
    units = number_units(claim, number)
    return any(find_quote(unit, place) for unit in units for place in places)


def locate(
    quote: str, cited: Passage, sources: Mapping[str, Passage]
) -> tuple[Passage, str] | None:
    """The passage a quote is in and its wording there: the cited passage, else the
    first other supplied passage holding it word for word (a wrong source id)."""
    for passage in (cited, *sources.values()):
        wording = find_quote(quote, passage.text)
        if wording is not None:
            return passage, wording
    return None


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
    if prices.states_price(draft.text):
        return Rejection(draft.text, "states a price")
    evidence = []
    cited = []
    for item in draft.evidence:
        passage = sources.get(item.source_id)
        if passage is None:
            return Rejection(draft.text, f"unknown source {item.source_id}")
        found = locate(item.quote, passage, sources)
        if found is None:
            return Rejection(
                draft.text, f"quote not in {item.source_id}: {item.quote!r}"
            )
        passage, quote = found
        cited.append(passage)
        evidence.append(
            Evidence(
                passage_id=passage.id,
                url=passage.url,
                title=passage.title,
                heading=passage.heading,
                quote=quote,
                link=source_link(passage, quote),
                fetched_at=passage.fetched_at,
            )
        )
    quoted = " ".join(item.quote for item in evidence)
    missing = [
        number
        for number in sorted(numbers(draft.text) - numbers(quoted))
        if not named_number(draft.text, number, cited)
    ]
    if missing:
        return Rejection(draft.text, f"number not in its quotes: {', '.join(missing)}")
    unquoted = sorted(regulation_terms(draft.text) - regulation_terms(quoted))
    if unquoted:
        return Rejection(
            draft.text, f"regulation not in its quotes: {', '.join(unquoted)}"
        )
    return Claim(draft.text, tuple(evidence), draft.part)


def verify(
    drafts: Sequence[DraftClaim], sources: Mapping[str, Passage]
) -> tuple[tuple[Claim, ...], tuple[Rejection, ...]]:
    """Split the model's claims into those to show and those removed, keeping order."""
    results = [check_claim(draft, sources) for draft in drafts]
    claims = tuple(result for result in results if isinstance(result, Claim))
    rejected = tuple(result for result in results if isinstance(result, Rejection))
    return claims, rejected

"""Claim verification policy. Invented passages only."""

from limespec.models import Claim, DraftClaim, DraftEvidence, Passage, Rejection
from limespec.verify import check_claim, find_quote, quote_link, verify

MORTAR = Passage(
    11,
    "https://example.test/products/mortex",
    "Mortex Mortar",
    "Mortex Mortar",
    "Mortex Mortar\nMortex suits joints of 3 to 6 mm.\nIt is a low-carbon mix.",
    "2026-09-12T10:00:00+00:00",
)
GUIDE = Passage(
    12,
    "https://example.test/support/guide",
    "Rendering Guide",
    "Drying",
    "Drying\nUneven colour is caused by uneven drying.\nThe Building Regulations "
    "apply to insulation work.",
    "2026-09-12T10:00:00+00:00",
)
SOURCES = {"S1": MORTAR, "S2": GUIDE}


def claim(text: str, *evidence: tuple[str, str]) -> DraftClaim:
    return DraftClaim(text, tuple(DraftEvidence(sid, quote) for sid, quote in evidence))


def reason(result: Claim | Rejection) -> str:
    assert isinstance(result, Rejection), result
    return result.reason


def test_a_valid_claim_and_exact_quote_produce_the_expected_citation() -> None:
    result = check_claim(
        claim("Mortex suits 3 to 6 mm joints.", ("S1", "suits joints of 3 to 6 mm")),
        SOURCES,
    )

    assert isinstance(result, Claim)
    assert result.text == "Mortex suits 3 to 6 mm joints."
    (evidence,) = result.evidence
    assert evidence.passage_id == 11
    assert evidence.url == "https://example.test/products/mortex"
    assert evidence.title == "Mortex Mortar"
    assert evidence.heading == "Mortex Mortar"
    assert evidence.quote == "suits joints of 3 to 6 mm"
    assert evidence.link == (
        "https://example.test/products/mortex"
        "#:~:text=suits%20joints%20of%203%20to%206%20mm"
    )
    assert evidence.fetched_at == "2026-09-12T10:00:00+00:00"


def test_quotes_may_differ_only_in_case_and_whitespace() -> None:
    # The citation shows the passage's own wording, not the model's.
    assert find_quote("MORTEX SUITS\n joints", MORTAR.text) == "Mortex suits joints"
    assert find_quote("Mortex Mortar Mortex suits", MORTAR.text) == (
        "Mortex Mortar\nMortex suits"
    )
    assert find_quote("Mortex fits joints", MORTAR.text) is None
    assert find_quote("  ", MORTAR.text) is None


def test_a_quote_must_start_and_end_at_word_edges() -> None:
    text = "Use it for joints of 3 to 60 mm."

    assert find_quote("joints of 3 to 6", text) is None
    assert find_quote("oints of 3", text) is None
    assert find_quote("joints of 3 to 60 mm.", text) == "joints of 3 to 60 mm."


def test_the_quote_link_escapes_text_fragment_syntax() -> None:
    link = quote_link("https://example.test/p", "low-carbon, lime & sand\nmix")

    assert link == (
        "https://example.test/p#:~:text=low%2Dcarbon%2C%20lime%20%26%20sand%20mix"
    )


def test_an_unknown_source_id_is_rejected() -> None:
    result = check_claim(
        claim("Mortex is low carbon.", ("S9", "low-carbon mix")), SOURCES
    )

    assert reason(result) == "unknown source S9"


def test_a_quote_absent_from_its_passage_drops_the_claim() -> None:
    # The words exist, but in S1, not in the passage the model cited.
    result = check_claim(
        claim("Mortex is low carbon.", ("S2", "low-carbon mix")), SOURCES
    )

    assert reason(result) == "quote not in S2: 'low-carbon mix'"


def test_one_bad_quote_drops_the_whole_claim() -> None:
    result = check_claim(
        claim(
            "Mortex is a low-carbon mix for thin joints.",
            ("S1", "It is a low-carbon mix."),
            ("S1", "Mortex is ideal for thin joints."),
        ),
        SOURCES,
    )

    assert reason(result).startswith("quote not in S1")


def test_a_claim_without_a_quote_is_rejected() -> None:
    assert reason(check_claim(claim("Mortex is strong."), SOURCES)) == "no quote"


def test_a_number_absent_from_the_evidence_drops_the_claim() -> None:
    # Also stops a number taken from the question: "4 mm" is within 3-6 mm, but no
    # quote says 4.
    result = check_claim(
        claim("Mortex suits 4 mm joints.", ("S1", "suits joints of 3 to 6 mm")),
        SOURCES,
    )

    assert reason(result) == "number not in its quotes: 4"


def test_a_number_must_keep_its_sign() -> None:
    frost = Passage(
        13, "u", "t", "h", "Do not apply below 5 °C or at −5 °C or +8 °C.", "d"
    )
    sources = {"S1": frost}

    flipped = check_claim(
        claim("It can be applied at -5 °C.", ("S1", "below 5 °C")), sources
    )
    same = check_claim(claim("Not at -5 °C.", ("S1", "at −5 °C")), sources)
    added_plus = check_claim(
        claim("It can be applied at +5 °C.", ("S1", "below 5 °C")), sources
    )
    same_plus = check_claim(claim("At +8 °C.", ("S1", "+8 °C")), sources)

    assert reason(flipped) == "number not in its quotes: -5"
    assert isinstance(same, Claim)  # a Unicode minus is the same sign
    assert reason(added_plus) == "number not in its quotes: +5"
    assert isinstance(same_plus, Claim)


def test_a_dash_between_numbers_is_a_range_not_a_sign() -> None:
    result = check_claim(
        claim("Mortex suits 3-6 mm joints.", ("S1", "joints of 3 to 6 mm")), SOURCES
    )

    assert isinstance(result, Claim)


def test_a_claim_adding_a_regulation_its_quotes_do_not_mention_is_dropped() -> None:
    # However the verdict is worded, it has to name the rule it passes or fails.
    product = ("S1", "It is a low-carbon mix.")

    verdict = check_claim(
        claim("This extension will comply with Part L.", product), SOURCES
    )
    approval = check_claim(claim("Building control will approve it.", product), SOURCES)

    assert reason(verdict) == "regulation not in its quotes: compliance, part l"
    assert reason(approval) == (
        "regulation not in its quotes: approval, building control"
    )


def test_a_regulation_named_in_the_quote_may_be_described() -> None:
    rules = Passage(
        14,
        "u",
        "t",
        "h",
        "You will need to comply with the Building Regulations, in particular "
        "Part L1B, when insulating walls.",
        "d",
    )
    quote = (
        "S1",
        "You will need to comply with the Building Regulations, in particular "
        "Part L1B, when insulating walls.",
    )

    result = check_claim(
        claim(
            "Insulating walls must be compliant with Part L of the regulations.", quote
        ),
        {"S1": rules},
    )

    assert isinstance(result, Claim)  # "compliant" = "comply"; "Part L" = "Part L1B"


def test_a_specific_rule_needs_that_rule_not_an_unrelated_regulation() -> None:
    other_rule = Passage(
        15, "u", "t", "h", "Environmental regulations may apply to the site.", "d"
    )
    result = check_claim(
        claim(
            "The Building Regulations apply.",
            ("S1", "Environmental regulations may apply"),
        ),
        {"S1": other_rule},
    )

    assert reason(result) == "regulation not in its quotes: building regulations"


def test_an_approval_absent_from_the_quote_is_dropped() -> None:
    result = check_claim(
        claim("Mortex has BBA approval.", ("S1", "It is a low-carbon mix.")), SOURCES
    )

    assert reason(result) == "regulation not in its quotes: approval"


def test_a_claim_supported_by_two_passages_keeps_both_sources() -> None:
    result = check_claim(
        claim(
            "Mortex is a low-carbon mix, and uneven drying causes uneven colour.",
            ("S1", "It is a low-carbon mix."),
            ("S2", "Uneven colour is caused by uneven drying."),
        ),
        SOURCES,
    )

    assert isinstance(result, Claim)
    assert [(e.passage_id, e.url) for e in result.evidence] == [
        (11, MORTAR.url),
        (12, GUIDE.url),
    ]


def test_verify_keeps_valid_claims_unchanged_and_records_each_removal() -> None:
    good = claim("Mortex is a low-carbon mix.", ("S1", "It is a low-carbon mix."))
    bad = claim("Mortex sets in 2 days.", ("S1", "It is a low-carbon mix."))

    claims, rejected = verify([good, bad], SOURCES)

    assert [c.text for c in claims] == ["Mortex is a low-carbon mix."]
    assert rejected == (
        Rejection("Mortex sets in 2 days.", "number not in its quotes: 2"),
    )

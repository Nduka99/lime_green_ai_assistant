"""Claim verification policy. Invented passages only."""

from limespec import lists, prices
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


def test_a_table_row_can_be_quoted_as_the_page_reads_it() -> None:
    row = "Reaction to fire | Class A1 | EN 998-1\nlime|green"

    # The " | " between cells is this project's mark, not the document's words.
    assert find_quote("Reaction to fire Class A1", row) == "Reaction to fire | Class A1"
    assert find_quote("fire | Class A1 | EN", row) == "fire | Class A1 | EN"
    assert find_quote("Reaction to | fire", row) is None  # no mark there
    assert find_quote("lime green", row) is None  # a bar in a word is its own


def test_the_page_s_typography_and_compatibility_forms_match_their_plain_forms() -> (
    None
):
    row = 'POCP ("smog") | kg C2H4e\n9" brick wall | U value\n3-6 mm | N/mm² | fine'

    assert find_quote("POCP (“smog”)", row) == 'POCP ("smog")'
    assert find_quote("9” brick wall", row) == '9" brick wall'
    assert find_quote("3–6 mm", row) == "3-6 mm"
    assert find_quote("N/mm2", row) == "N/mm²"
    assert find_quote("ﬁne", row) == "fine"


def test_spacing_may_differ_where_a_digit_meets_a_non_digit() -> None:
    text = "Water absorption | 0.8kg/(m 2 .min 0.5 ) | 1 to 3 N/mm 2 | EN 1015-11"

    assert find_quote("0.8kg/(m2.min0.5)", text) == "0.8kg/(m 2 .min 0.5 )"
    assert find_quote("1 to 3 N/mm2", text) == "1 to 3 N/mm 2"
    assert find_quote("EN1015-11", text) == "EN 1015-11"


def test_spacing_between_letters_or_digits_and_within_numbers_is_kept() -> None:
    assert find_quote("36 mm", "3 6 mm") is None
    assert find_quote("1.5 kg", "Step 1. 5 kg") is None
    assert find_quote("1, 2", "1,2 m") is None
    assert find_quote("1,2 m", "1, 2 m") is None
    assert find_quote("therapist", "the rapist") is None
    assert find_quote("the rapist", "therapist") is None
    assert find_quote("3 to 6", "joints of 3 to 60 mm") is None
    assert find_quote("oints", "joints") is None


def test_the_quote_link_escapes_text_fragment_syntax() -> None:
    link = quote_link("https://example.test/p", "low-carbon, lime  & sand mix")

    assert link == (
        "https://example.test/p#:~:text=low%2Dcarbon%2C%20lime%20%26%20sand%20mix"
    )


def test_a_quote_over_several_lines_links_as_a_range() -> None:
    # A text directive matches inside one block of the page: a heading and its text,
    # or two list items, are linked from the first line to the last.
    link = quote_link("https://example.test/p", "Uses\n\nRepointing, brick-work")

    assert link == "https://example.test/p#:~:text=Uses,Repointing%2C%20brick%2Dwork"


def test_a_quote_from_a_pdf_links_to_its_page() -> None:
    assert quote_link("https://example.test/a.pdf", "lime", 3) == (
        "https://example.test/a.pdf#page=3"
    )


def test_an_address_with_spaces_is_percent_encoded_once() -> None:
    url = "https://example.test/Documents/carbon footprint - solo.pdf?v=1 2"
    done = "https://example.test/Documents/carbon%20footprint%20-%20solo.pdf?v=1%202"

    assert quote_link(url, "lime", 3) == f"{done}#page=3"
    assert quote_link(done, "lime", 3) == f"{done}#page=3"  # escapes kept as they are


def test_an_unknown_source_id_is_rejected() -> None:
    result = check_claim(
        claim("Mortex is low carbon.", ("S9", "low-carbon mix")), SOURCES
    )

    assert reason(result) == "unknown source S9"


def test_a_quote_in_no_supplied_passage_drops_the_claim() -> None:
    result = check_claim(
        claim("Mortex is low carbon.", ("S2", "zero-carbon mix")), SOURCES
    )

    assert reason(result) == "quote not in S2: 'zero-carbon mix'"


def test_a_quote_cited_to_the_wrong_passage_is_cited_to_the_one_holding_it() -> None:
    # The words exist, but in S1, not in the passage the model cited.
    result = check_claim(
        claim("Mortex is low carbon.", ("S2", "low-carbon mix")), SOURCES
    )

    assert isinstance(result, Claim)
    (evidence,) = result.evidence
    assert evidence.passage_id == MORTAR.id and evidence.quote == "low-carbon mix"


def test_a_number_in_a_name_is_supported_by_the_cited_passage_holding_the_name() -> (
    None
):
    primer = Passage(
        14,
        "u",
        "Silic8 MPL1 Primer",
        "Silic8 MPL1 Primer",
        "A gritted primer. Certified to ISO 9001:2015. Add 25kg to the mixer.",
        "d",
    )
    sources = {"S1": primer}

    names = check_claim(
        claim("Silic8 MPL1 is gritted.", ("S1", "A gritted primer")), sources
    )
    standard = check_claim(
        claim("It is ISO 9001 certified.", ("S1", "primer")), sources
    )
    joined = check_claim(claim("Mix 25 kg bags.", ("S1", "primer")), sources)
    alone = check_claim(claim("Mix it into 25 bags.", ("S1", "primer")), sources)
    other = check_claim(claim("Silic8 MPL2 is gritted.", ("S1", "primer")), sources)

    assert isinstance(names, Claim)
    assert isinstance(standard, Claim)  # "ISO 9001" is in the passage's text
    assert reason(joined) == "number not in its quotes: 25"  # "Mix 25" is not
    assert reason(alone) == "number not in its quotes: 25"  # "into 25" is not
    assert reason(other) == "number not in its quotes: 2"  # MPL2 is not MPL1


def test_a_joined_number_matches_its_token_and_decimals_stay_whole() -> None:
    passage = Passage(
        15, "u", "Mortar", "Mixing", "Add 25kg to 5 litres of water.", "d"
    )
    sources = {"S1": passage}

    joined = check_claim(claim("Add 25kg to it.", ("S1", "of water")), sources)
    decimal = check_claim(claim("Add 1.5 litres.", ("S1", "of water")), sources)
    start = check_claim(claim("5 litres of water.", ("S1", "of water")), sources)

    assert isinstance(joined, Claim)
    assert reason(decimal) == "number not in its quotes: 1.5"
    assert reason(start) == "number not in its quotes: 5"  # no word before it


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


def test_the_price_rule_finds_currency_amounts_only() -> None:
    for text in ["£5.00", "a £ 18 bag", "$10", "€2.50 each", "5 GBP", "12.5EUR"]:
        assert prices.states_price(text), text
    for text in ["VAT is added", "£ per bag", "5 bags of 25kg", "GBP", "the $ sign"]:
        assert not prices.states_price(text), text


def test_price_sentences_leave_a_passage_and_the_rest_stays() -> None:
    text = (
        "Samples\nThey used Solo (£18 for 25kg). Always wear gloves.\n"
        "£5.00\nNo price here.  Two spaces stay."
    )

    assert prices.without_prices(text) == (
        "Samples\nAlways wear gloves.\nNo price here.  Two spaces stay."
    )


def test_a_claim_stating_a_price_is_removed_even_with_its_quote() -> None:
    sample = Passage(
        13,
        "https://example.test/order-a-sample",
        "Order Samples",
        "Our samples",
        "Our samples\nMortex sample £5.00",
        "2026-09-12T10:00:00+00:00",
    )

    result = check_claim(
        claim("A Mortex sample costs £5.00.", ("S3", "Mortex sample £5.00")),
        {"S3": sample},
    )

    assert reason(result) == "states a price"


def test_a_compiled_list_is_cited_by_its_page_without_a_highlight() -> None:
    compiled = Passage(
        13,
        "https://example.test/products-by-colour/cinders",
        "Cinders",
        lists.HEADING,
        lists.list_passage("Cinders", ["Ashlar Lime Mortar", "Contour Repair"]),
        "2026-09-29T10:00:00+00:00",
    )

    result = check_claim(
        claim("Cinders comes in Ashlar Lime Mortar.",
              ("S1", "Ashlar Lime Mortar; Contour Repair")),
        {"S1": compiled},
    )  # fmt: skip

    assert isinstance(result, Claim)
    assert result.evidence[0].link == "https://example.test/products-by-colour/cinders"


def test_a_word_file_is_cited_at_its_plain_address() -> None:
    from limespec.models import Passage
    from limespec.verify import source_link

    passage = Passage(
        1, "https://example.test/Docs/EC DoP.docx", "DoP", "", "A1", "", 1
    )

    assert source_link(passage, "A1") == "https://example.test/Docs/EC%20DoP.docx"

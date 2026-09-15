"""What a reader sees: numbered sources, fixed notices, never a removed claim."""

from limespec.answer import SAFETY_REFERRAL
from limespec.models import Answer
from limespec.view import view


def test_each_distinct_quote_becomes_one_numbered_source(answered: Answer) -> None:
    result = view(answered)

    assert [claim["sources"] for claim in result["claims"]] == [[1], [1, 2]]
    first, second = result["sources"]
    assert first["number"] == 1
    assert (first["title"], first["heading"]) == ("Mortex Mortar", "Uses")
    assert first["quote"] == "suits joints of 3 to 6 mm"
    assert first["link"].startswith("https://example.test/products/mortex#:~:text=")
    assert first["captured"] == "2026-09-12"
    assert second["quote"] == "Uneven colour is caused by uneven drying."  # one line


def test_a_claim_removed_by_verification_never_appears(answered: Answer) -> None:
    result = view(answered)

    assert "rejected" not in result
    assert "Mortex is cheap" not in str(result)


def test_only_a_refusal_lists_the_closest_pages(
    answered: Answer, insufficient: Answer
) -> None:
    assert view(answered)["closest_pages"] == []
    assert view(insufficient)["closest_pages"] == [
        {"title": "Mortex Mortar", "url": "https://example.test/products/mortex"},
        {"title": "Rendering Guide", "url": "https://example.test/support/guide"},
    ]


def test_a_safety_referral_is_the_fixed_text_alone(referral: Answer) -> None:
    result = view(referral)

    assert result["status"] == "safety_referral"
    assert result["notice"] == SAFETY_REFERRAL
    assert result["claims"] == [] and result["sources"] == []
    assert result["closest_pages"] == []

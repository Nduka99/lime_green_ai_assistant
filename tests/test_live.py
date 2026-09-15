"""Live smoke test: the three kinds of question the brief asks for, answered by
the running llama.cpp servers from the built index.

Deselected by default; with the three servers running, run
`uv run pytest -m live --no-cov`. These questions are separate from the ones in
the results notebook.
"""

import pytest

from limespec import assistant

pytestmark = pytest.mark.live


def test_a_straightforward_product_question_is_answered_with_its_source() -> None:
    result = assistant.ask("What is Grippa used for?")

    assert result.status == "answered"
    assert all(claim.evidence for claim in result.claims)


def test_a_question_needing_two_sources_cites_both_pages_or_warns() -> None:
    result = assistant.ask(
        "What is Hemp Lime Binder used for, and what is Contour for?"
    )

    pages = {evidence.url for claim in result.claims for evidence in claim.evidence}
    assert result.status == "answered"
    # A part left without a verified claim is never hidden: the caution says so.
    assert len(pages) >= 2 or result.notice


def test_a_question_the_pages_cannot_answer_gets_the_fixed_refusal() -> None:
    result = assistant.ask("How much does a tub of Grippa cost?")

    assert result.status == "insufficient_evidence"
    assert result.claims == ()

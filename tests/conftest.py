import re
import zlib
from pathlib import Path

import pytest

from limespec.answer import INSUFFICIENT, PARTIAL, SAFETY_REFERRAL
from limespec.models import Answer, Claim, Evidence, Passage, Rejection
from limespec.retrieve import Embed, Rerank
from limespec.verify import quote_link

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_URLS = {
    "product.html": "https://example.test/products/mortex",
    "faq.html": "https://example.test/support/faq",
    "category.html": "https://example.test/products/base-coats",
    "article.html": "https://example.test/support/checklist",
}


def word_counts(text: str) -> list[float]:
    """A deterministic stand-in for an embedding: hashed word counts."""
    vector = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32(word.encode()) % 64] += 1
    return vector


@pytest.fixture
def fake_embed() -> Embed:
    return lambda texts: [word_counts(text) for text in texts]


@pytest.fixture
def fake_rerank() -> Rerank:
    """A stand-in reranker: equal scores for every passage keep the fused order."""
    return lambda query, documents: [0.0] * len(documents)


@pytest.fixture
def fixture_pages() -> list[tuple[str, bytes, str]]:
    """(url, raw_bytes, fetched_at) for every hand-written fixture page."""
    return [
        (url, (FIXTURES / name).read_bytes(), "2026-09-12T10:00:00+00:00")
        for name, url in FIXTURE_URLS.items()
    ]


# Invented answers for the interface tests: what `answer()` can return.
MORTEX = Passage(
    1,
    "https://example.test/products/mortex",
    "Mortex Mortar",
    "Uses",
    "Uses\nMortex suits joints of 3 to 6 mm.",
    "2026-09-12T10:00:00+00:00",
)
GUIDE = Passage(
    2,
    "https://example.test/support/guide",
    "Rendering Guide",
    "Drying",
    "Drying\nUneven colour is caused by\nuneven drying.",
    "2026-09-12T10:00:00+00:00",
)


def evidence(passage: Passage, quote: str) -> Evidence:
    return Evidence(
        passage.id,
        passage.url,
        passage.title,
        passage.heading,
        quote,
        quote_link(passage.url, quote),
        passage.fetched_at,
    )


@pytest.fixture
def answered() -> Answer:
    """Two claims sharing one quote, with a removed claim that must never show."""
    joints = evidence(MORTEX, "suits joints of 3 to 6 mm")
    drying = evidence(GUIDE, "Uneven colour is caused by\nuneven drying.")
    return Answer(
        "What joints does Mortex suit?",
        "answered",
        PARTIAL,
        (
            Claim("Mortex suits 3 to 6 mm joints.", (joints,)),
            Claim("Mortex suits thin joints; drying affects colour.", (joints, drying)),
        ),
        (MORTEX, GUIDE),
        (Rejection("Mortex is cheap.", "quote not in S1: 'Mortex is cheap.'"),),
    )


@pytest.fixture
def insufficient() -> Answer:
    return Answer(
        "What does Mortex cost?",
        "insufficient_evidence",
        INSUFFICIENT,
        (),
        (MORTEX, MORTEX, GUIDE),
        (),
    )


@pytest.fixture
def referral() -> Answer:
    return Answer(
        "my son swallowed some mortar", "safety_referral", SAFETY_REFERRAL, (), (), ()
    )

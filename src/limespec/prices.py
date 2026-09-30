"""Prices are never stated from indexed text (experiment X16).

A price found in a page can be stale, a third party's, or belong to another
product: indexing the sample-order page once made the assistant quote a sample
price for an unrelated product (development repo, D46). So the sentences that
state a currency amount are left out of a passage before it is indexed (E5: the
whole passage used to be hidden, and with it everything else it said), a passage
that still contains one is tagged when it is stored and never searched, and a
claim that states one is removed. All use this one rule, and so does the
evaluation's guardrail check.
"""

import re

from limespec.passages import SENTENCE_END

# A currency symbol next to a digit (£5, $ 10, €2.50), or a number followed by a
# currency code (5 GBP). db/migrations/20260928200000_commercial_passages.sql
# repeats this pattern in Postgres's syntax to tag passages stored before it.
CURRENCY_AMOUNT = re.compile(r"[£$€¥]\s?[0-9]|[0-9]\s?(?:GBP|EUR|USD)\b")


def states_price(text: str) -> bool:
    """Whether the text contains a currency amount."""
    return CURRENCY_AMOUNT.search(text) is not None


def without_prices(text: str) -> str:
    """The text without its sentences that state a price. A line with no price is
    kept as it is; a line left with no sentence is dropped."""
    kept = []
    for line in text.split("\n"):
        if not states_price(line):
            kept.append(line)
            continue
        rest = [s for s in SENTENCE_END.split(line) if not states_price(s)]
        if rest:
            kept.append(" ".join(rest))
    return "\n".join(kept)

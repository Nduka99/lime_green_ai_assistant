"""Which products a question names, so a search can be repeated inside them (E5 B4).

Many documents share most of their text across products (safety data sheets: 17% of
passages repeat another document's text), and the right product's copy can rank far
below the others. Searching again inside the named product's own documents finds it.

A passage's scope is its title up to " — ": a web page's title, or, for a PDF, the
title of the product page linking it ("Silic8 AD2 — Data Sheet"). A product is named
when each of its name's distinctive words (a word in at most `DISTINCT` product names)
is in the question, with spaces and hyphens ignored, so "Mesh Coat" finds "Meshcoat".
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence

SEPARATOR = " — "
DISTINCT = 2  # a name word shared by at most this many product names identifies one


def scope_of(title: str) -> str:
    """The product or page a passage belongs to."""
    return title.split(SEPARATOR, 1)[0]


def name_words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1]


def naming(names: Sequence[str]) -> Callable[[str], list[str]]:
    """A function giving the product names a question names, in `names`' order."""
    counts = Counter(word for name in names for word in set(name_words(name)))
    marks = {}
    for name in names:
        marks[name] = [word for word in name_words(name) if counts[word] <= DISTINCT]

    def named(question: str) -> list[str]:
        squashed = re.sub(r"[^a-z0-9]", "", question.lower())
        found = []
        for name, words in marks.items():
            if words and all(word in squashed for word in words):
                found.append(name)
        return found

    return named

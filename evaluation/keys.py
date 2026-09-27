"""Check an answer key written by an independent key writer, and make the blind
question file the systems answer.

Checking prints only counts and problems, never answers, so it cannot shape the
system under test. Every evidence quote must appear as continuous text on its
cached page: the page's visible text, or an image's alt text for `image_alt`
evidence. The blind file holds ids and question text only, shuffled with a fixed
seed, so the order says nothing about the cases.
"""

import random
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup

STATUSES = {"answered", "insufficient_evidence", "safety_referral"}
ReadPage = Callable[[str], str | None]  # url -> cached HTML, or None if not cached


def normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def page_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return normalise(soup.get_text(" "))


def alt_texts(raw: str) -> list[str]:
    soup = BeautifulSoup(raw, "html.parser")
    return [normalise(str(img.get("alt", ""))) for img in soup.find_all("img")]


def quote_found(evidence: dict[str, Any], raw: str) -> bool:
    quote = normalise(evidence.get("quote", ""))
    if not quote:
        return False
    if evidence.get("kind") == "image_alt":
        return any(quote in alt for alt in alt_texts(raw))
    return quote in page_text(raw)


def problems(key: dict[str, Any], read_page: ReadPage) -> tuple[list[str], set[str]]:
    """Problems in the key, and the cited pages missing from the cache.

    Every case must use the same wording styles as the first case, so no case is
    asked in more or easier ways than another.
    """
    found: list[str] = []
    missing: set[str] = set()
    cases = key.get("cases", [])
    ids = [case.get("id") for case in cases]
    if len(set(ids)) != len(ids):
        found.append("case ids are not unique")
    expected_styles = (
        sorted(w.get("style") for w in cases[0]["wordings"]) if cases else []
    )
    for case in cases:
        cid = case.get("id", "?")
        if case.get("expected_status") not in STATUSES:
            found.append(f"{cid}: unknown expected_status")
        styles = sorted(w.get("style") for w in case.get("wordings", []))
        if styles != expected_styles:
            found.append(f"{cid}: wordings are {styles}, not {expected_styles}")
        for part in case.get("parts", []):
            for evidence in part.get("evidence", []):
                url = evidence.get("page_url") or evidence.get("url", "")
                raw = read_page(url)
                if raw is None:
                    missing.add(url)
                elif not quote_found(evidence, raw):
                    found.append(
                        f"{cid} {part.get('id', '?')}: a quote is not on {url}"
                    )
    return found, missing


def blind_questions(
    key: dict[str, Any], seed: int, prefix: str
) -> list[dict[str, str]]:
    """Every wording as {"id", "question"}, shuffled with the seed."""
    rows = [w["text"] for case in key["cases"] for w in case["wordings"]]
    random.Random(seed).shuffle(rows)
    return [
        {"id": f"{prefix}{n:03d}", "question": text} for n, text in enumerate(rows, 1)
    ]

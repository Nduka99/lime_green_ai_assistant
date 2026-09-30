"""E8's specialist arm: OCC-RAG as a per-part answerability gate. The model server is
a stand-in that states a status after a short analysis."""

import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import abstainer, graders
from limespec import assistant, store
from limespec.models import Passage

SOLO = Passage(
    7, "https://example.test/solo", "Solo", "Drying", "Dries in 2 days.", "d"
)
ITEMS = [
    {"id": "p7/a1", "case": "p7", "parts": ["How long does Solo dry?", "Is it grey?"]},
    {"id": "p7/n1", "case": "p7", "parts": ["What does Solo cost?"]},
]


def position(
    token: str, *candidates: tuple[str, float], token_id: int = 1
) -> dict[str, Any]:
    tops = [{"token": t, "logprob": p} for t, p in candidates]
    return {"id": token_id, "token": token, "top_logprobs": tops}


MARK = position("", ("", 0.0), token_id=abstainer.STATUS_START)  # written as empty text


def status(yes: float, no: float) -> list[dict[str, Any]]:
    """An analysis, the status mark, a line break, then the status's two readings."""
    return [
        position("The source", ("The source", -0.1)),
        MARK,
        position("\n", ("\n", 0.0)),
        position("ANS", ("ANS", math.log(yes)), (" UN", math.log(no)), ("The", -9.0)),
    ]


def server(bodies: list[dict[str, Any]]) -> graders.Send:
    """Answerable only for drying questions."""

    def send(body: dict[str, Any]) -> dict[str, Any]:
        bodies.append(body)
        text = body["messages"][0]["content"]
        chances = (0.9, 0.1) if "dry" in text else (0.2, 0.8)
        return {"choices": [{"logprobs": {"content": status(*chances)}}]}

    return send


def test_the_prompt_is_the_models_own_format() -> None:
    text = abstainer.prompt("How long?", ["Solo: Dries in 2 days.", "Duro: Sets."])

    assert text == (
        "<|query_start|>How long?<|query_end|>\n"
        "<|source_start|><|source_id|>1 Solo: Dries in 2 days.<|source_end|>\n"
        "<|source_start|><|source_id|>2 Duro: Sets.<|source_end|>\n"
    )
    body = abstainer.body("How long?", ["Solo"])
    assert body["temperature"] == 0.0 and body["logprobs"] is True


def test_the_score_is_answerable_against_unanswerable_at_the_status() -> None:
    assert abstainer.answerable(status(0.6, 0.2)) == pytest.approx(0.75)
    assert abstainer.answerable(status(0.6, 0.2)[:3]) == 0.5  # cut before the status
    assert abstainer.answerable([position("x", ("x", 0.0))]) == 0.5
    neither = [MARK, position("Maybe", ("Maybe", 0.0), ("Perhaps", -2.0))]
    assert abstainer.answerable(neither) == 0.5


def test_a_missing_reading_gets_the_lowest_listed_chance() -> None:
    sure = [MARK, position("UN", ("UN", 0.0), ("Un", -9.0), ("No", -12.0))]

    assert 0 < abstainer.answerable(sure) == pytest.approx(math.exp(-12.0), rel=1e-3)


def test_a_claim_scores_its_best_part() -> None:
    bodies: list[dict[str, Any]] = []
    texts = {"p7/a1": ["Solo: Dries in 2 days."], "p7/n1": ["Solo: Dries in 2 days."]}

    scores = abstainer.by_parts(ITEMS, texts, server(bodies))

    assert scores == {"p7/a1": pytest.approx(0.9), "p7/n1": pytest.approx(0.2)}
    assert len(bodies) == 3


def test_sources_are_read_as_where_they_stand_then_what_they_say() -> None:
    quoted = abstainer.quoted(
        {"c1": [["Solo", "Drying", "2 days"], ["Solo", "Solo", "Lime"]]}
    )

    assert quoted == {"c1": ["Solo › Drying: 2 days", "Solo: Lime"]}
    assert abstainer.whole(ITEMS[:1], {"p7": SOLO}) == {
        "p7/a1": ["Solo › Drying: Dries in 2 days."]
    }


def test_the_command_line_scores_quotes_or_whole_passages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = tmp_path / "items.json"
    items.write_text(json.dumps(ITEMS))
    slots = tmp_path / "slots.json"
    cited = [["Solo", "Drying", "Dries in 2 days."]]
    slots.write_text(json.dumps({"sources": {"p7/a1": cited, "p7/n1": cited}}))

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "load_passages", lambda conn, ids: [SOLO])
    monkeypatch.setattr(graders, "post_to", lambda url: server([]))
    command = ["claim-answerable", str(items), "--url", "http://gate"]

    for where in (["--sources", str(slots)], ["--passages"]):
        out = tmp_path / "scores.json"
        assert cli.main([*command, *where, "--out", str(out)]) == 0
        assert json.loads(out.read_text())["p7/a1"] == pytest.approx(0.9)

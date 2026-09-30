"""E7 S1: slot matching on the claim benchmark. Every claim, source, slot and score is
invented; the model servers are stand-ins."""

import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import slotbench
from limespec import assistant, llm, store

SOLO = {
    "number": 1,
    "title": "Solo — Data",
    "heading": "Drying",
    "quote": "Dries in 2 days.",
}
DURO = {"number": 2, "title": "Duro", "heading": "Duro", "quote": "Duro dries fast."}
PAIRS = [
    {"id": "q1", "question": "How long does Solo take to dry?",
     "A": {"claims": [{"text": "Solo dries in 2 days.", "sources": [1]},
                      {"text": "Duro dries fast.", "sources": [2]}],
           "sources": [SOLO, DURO]}},
]  # fmt: skip
PART = "How long does Solo take to dry?"
ITEMS = [
    {"id": "demo/q1/A1", "case": "demo/k1", "parts": [PART],
     "claim": "Solo dries in 2 days.", "quotes": [SOLO["quote"]], "label": "correct"},
    {"id": "demo/q1/A2", "case": "demo/k1", "parts": [PART],
     "claim": "Duro dries fast.", "quotes": [DURO["quote"]], "label": "off_question"},
]  # fmt: skip
SOLO_KEY = "Solo — Data\nDrying\nDries in 2 days."
DURO_KEY = "Duro\nDuro\nDuro dries fast."
EXTRACTED = {
    "asked": {PART: [{"subject": "Solo", "property": "drying time"}]},
    "stated": {
        SOLO_KEY: [{"subject": "Solo", "property": "drying time"}],
        DURO_KEY: [{"subject": "Duro", "property": "drying speed"}],
    },
}  # fmt: skip


def slot_reply(count: int, subject: str) -> dict[str, Any]:
    item = {"slots": [{"subject": subject, "property": "drying time"}]}
    return {"items": [item] * count}


def test_each_claim_gets_its_sources_back_from_the_blind_pairs() -> None:
    sources = slotbench.claim_sources(ITEMS, {"demo": PAIRS})

    assert sources["demo/q1/A1"] == [("Solo — Data", "Drying", "Dries in 2 days.")]
    assert sources["demo/q1/A2"] == [("Duro", "Duro", "Duro dries fast.")]


def test_parts_are_read_per_question_and_sources_in_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(slotbench, "BATCH", 1)
    users: list[str] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        users.append(user)
        count = schema["properties"]["items"]["minItems"]
        return slot_reply(count, "Solo")

    sources = slotbench.claim_sources(ITEMS, {"demo": PAIRS})
    found = slotbench.extract(ITEMS, sources, chat)

    assert len(users) == 3  # one question, then two sources one at a time
    assert set(found["stated"]) == {SOLO_KEY, DURO_KEY}
    assert found["asked"]["How long does Solo take to dry?"][0]["subject"] == "Solo"


def test_the_product_check_fails_a_claim_only_from_other_products() -> None:
    sources = slotbench.claim_sources(ITEMS, {"demo": PAIRS})

    scores = slotbench.by_product(ITEMS, sources, lambda part: ["Solo"])

    assert scores == {"demo/q1/A1": 1.0, "demo/q1/A2": 0.0}
    assert slotbench.by_product(ITEMS, sources, lambda part: []) == {
        "demo/q1/A1": 1.0,
        "demo/q1/A2": 1.0,
    }


def test_a_claim_scores_its_best_pair_by_the_reranker() -> None:
    sources = slotbench.claim_sources(ITEMS, {"demo": PAIRS})
    queried: list[tuple[str, list[str]]] = []

    def rerank(query: str, documents: list[str]) -> list[float]:
        queried.append((query, documents))
        return [2.0 if d.startswith("Solo") else -1.0 for d in documents]

    scores = slotbench.by_pairs(
        ITEMS, sources, EXTRACTED, slotbench.reranker_pairs(rerank)
    )

    assert scores == {"demo/q1/A1": 2.0, "demo/q1/A2": -1.0}
    assert queried[0] == ("Solo: drying time", ["Solo: drying time"])


def position(token: str, yes: float, no: float) -> dict[str, Any]:
    return {
        "token": token,
        "top_logprobs": [
            {"token": '"yes', "logprob": yes},
            {"token": "no", "logprob": no},
        ],
    }


def test_the_judge_s_yes_probability_is_read_where_it_answers() -> None:
    generated = [
        {"token": '{"answers":[', "top_logprobs": []},
        position('"yes', math.log(0.9), math.log(0.1)),
        position('","', 0.0, 0.0),
        position("no", math.log(0.2), math.log(0.8)),
        {"token": "maybe", "top_logprobs": [{"token": "yes", "logprob": 0.0}]},
    ]

    found = slotbench.yes_probabilities(generated)

    assert found == pytest.approx([0.9, 0.2])
    lone = [{"token": "yes", "top_logprobs": [{"token": "yes", "logprob": 0.0}]}]
    assert slotbench.yes_probabilities(lone) == [1.0]


def test_the_judge_asks_every_pair_of_a_claim_in_one_request() -> None:
    sent: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append(kwargs["json"])
        body = {"choices": [{"logprobs": {"content": [position("yes", 0.0, -9.0)]}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    score = slotbench.judge_pairs(post)

    assert score([("Solo: drying time", "Solo: drying time")]) == pytest.approx(
        [1.0], abs=1e-3
    )
    assert (
        "1. A: Solo: drying time\n   B: Solo: drying time"
        in sent[0]["messages"][1]["content"]
    )
    assert sent[0]["logprobs"] is True
    with pytest.raises(llm.ModelServerError, match="does not match its pairs"):
        score([("a", "b"), ("c", "d")])


def test_a_failed_product_check_scores_below_every_phrase_score() -> None:
    gated = slotbench.gated({"a": 1.0, "b": 0.0}, {"a": 0.3, "b": 0.9})

    assert gated == {"a": 0.3, "b": -0.7}


def test_the_command_line_extracts_compares_and_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sitting = tmp_path / "sitting"
    sitting.mkdir()
    (sitting / "pairs.json").write_text(json.dumps(PAIRS), encoding="utf-8")
    items = tmp_path / "items.json"
    items.write_text(json.dumps(ITEMS), encoding="utf-8")

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        return slot_reply(schema["properties"]["items"]["minItems"], "Solo")

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(llm, "rerank", lambda q, docs: [1.0] * len(docs))
    monkeypatch.setattr(slotbench, "judge_pairs", lambda post: lambda p: [0.5] * len(p))
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "product_names", lambda conn, version: ["Solo"])
    extracted = tmp_path / "slots.json"
    base = ["--items", str(items)]

    assert cli.main(["slot-extract", *base, "--set", "demo", str(sitting),
                     "--out", str(extracted)]) == 0  # fmt: skip
    outs = {}
    for by in ("product", "reranker", "judge"):
        outs[by] = tmp_path / f"{by}.json"
        command = ["slot-compare", str(extracted), *base, "--by", by]
        assert cli.main([*command, "--version", "17", "--out", str(outs[by])]) == 0
    gated = tmp_path / "gated.json"
    assert cli.main(["slot-gate", str(outs["product"]), str(outs["judge"]),
                     "--out", str(gated)]) == 0  # fmt: skip

    assert "1 parts and 2 sources read" in capsys.readouterr().out
    assert json.loads(outs["product"].read_text()) == {
        "demo/q1/A1": 1.0,
        "demo/q1/A2": 0.0,
    }
    assert json.loads(gated.read_text()) == {"demo/q1/A1": 0.5, "demo/q1/A2": -0.5}

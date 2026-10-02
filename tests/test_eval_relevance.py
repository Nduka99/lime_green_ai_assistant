"""The relevance benchmark: items from answer runs, candidates, scores. Every answer,
claim and model reply here is invented."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import metrics, relevance
from limespec import answer, config, llm
from limespec.models import Part

SOURCES = [
    {"number": 1, "quote": "Duro is free of cement."},
    {"number": 2, "quote": "Duro costs less."},
]
RECORDS: list[dict[str, Any]] = [
    {"id": "q1", "question": "Is Duro free of cement?",
     "view": {"claims": [{"text": "Duro has no cement.", "sources": [1]},
                         {"text": "Duro is cheap.", "sources": [1, 2]}],
              "sources": SOURCES}},
    {"id": "q2", "question": "Refused?", "view": {"claims": [], "sources": []}},
    {"id": "q3", "http": None, "error": "refused"},
]  # fmt: skip
ITEM = {
    "id": "q1",
    "parts": ["Is Duro free of cement?"],
    "claims": [
        {"text": "Duro has no cement.", "quotes": ["Duro is free of cement."]},
        {
            "text": "Duro is cheap.",
            "quotes": ["Duro is free of cement.", "Duro costs less."],
        },
    ],
}


def test_items_hold_each_answer_s_parts_and_claims_with_their_quotes() -> None:
    assert relevance.items(RECORDS, lambda q: [q]) == [ITEM]


def test_the_prompt_numbers_claims_as_c3_did_or_letters_them_as_c3p_did() -> None:
    numbered = relevance.user_prompt(ITEM, lettered=False)
    lettered = relevance.user_prompt(ITEM, lettered=True)

    assert numbered.startswith("Parts of the question:\n1. Is Duro free of cement?\n")
    assert '\n1. Duro has no cement.\n   Quotes: "Duro is free of cement."' in numbered
    assert "Claim B: Duro is cheap." in lettered


def test_each_model_candidate_sends_its_own_request() -> None:
    c3 = relevance.payload("c3", ITEM)
    think = relevance.payload("think128", ITEM)

    assert c3["messages"][0]["content"] == relevance.C3_PROMPT
    assert c3["chat_template_kwargs"]["enable_thinking"] is False
    assert c3["cache_prompt"] is False
    c3_items = c3["response_format"]["json_schema"]["schema"]["properties"]["parts"]
    assert c3_items["minItems"] == 2 and c3_items["items"]["maximum"] == 1
    assert think["messages"][0]["content"] == relevance.C3P_PROMPT
    assert think["chat_template_kwargs"] == {"enable_thinking": True}
    assert think["reasoning_budget_tokens"] == 128
    words_first = think["response_format"]["json_schema"]["schema"]["properties"]
    assert list(words_first["claims"]["items"]["properties"]) == ["answers", "part"]


def reply(content: object) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def test_replies_are_read_as_one_part_number_per_claim() -> None:
    assert relevance.parse("c3", reply({"parts": [1, 0]})) == [1, 0]
    checks = {"claims": [{"answers": "x", "part": 1}, {"answers": "none", "part": 0}]}
    assert relevance.parse("c3p", reply(checks)) == [1, 0]


def test_a_model_candidate_and_the_reranker_are_run_item_by_item() -> None:
    sent: list[dict[str, Any]] = []

    def send(body: dict[str, Any]) -> dict[str, Any]:
        sent.append(body)
        return reply({"parts": [1, 0]})

    def rerank(query: str, texts: list[str]) -> list[float]:
        return [0.9, -2.0] if "cement" in query else [0.1, 0.5]

    found = relevance.check("c3", [ITEM], send)
    scored = relevance.check("rerank", [ITEM | {"parts": ["cement?", "cost?"]}],
                             rerank=rerank)  # fmt: skip

    assert found[0]["parts"] == [1, 0] and found[0]["id"] == "q1"
    assert len(sent) == 1 and found[0]["seconds"] >= 0
    assert scored[0]["scores"] == [0.9, 0.5]  # the best part for each claim


def test_the_generator_is_asked_through_the_shared_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        assert url == config.CHAT_URL
        return httpx.Response(200, json=reply({"parts": [1]}),
                              request=httpx.Request("POST", url))  # fmt: skip

    monkeypatch.setattr(llm.CLIENT, "post", post)

    assert relevance.post({"messages": []}) == reply({"parts": [1]})


def test_candidates_are_scored_on_claims_wrongly_and_rightly_removed() -> None:
    labels = {"q1": [1, 0], "q2": [2, 1]}
    results = [
        {"id": "q1", "parts": [0, 0], "seconds": 1.0},  # one wrong, one right
        {"id": "q2", "parts": [1, 1], "seconds": 3.0},  # a claim given another part
    ]

    assert relevance.score(labels, results) == {
        "items": 2, "median_seconds": 2.0, "relevant": 3, "irrelevant": 1,
        "wrongly_removed": 1, "rightly_removed": 1, "other_part": 1,
    }  # fmt: skip


def test_the_reranker_is_scored_by_how_well_its_scores_separate_the_labels() -> None:
    labels = {"q1": [1, 0, 1]}
    results = [{"id": "q1", "scores": [0.9, 0.2, 0.2], "seconds": 0.1}]

    found = relevance.score(labels, results)

    assert found["auc"] == pytest.approx(0.75)  # 0.9 > 0.2, 0.2 ties 0.2


def test_auc_needs_both_labels() -> None:
    assert metrics.auc([(1.0, True), (0.0, False)]) == 1.0
    assert metrics.auc([(1.0, True)]) == 0.0


def test_the_command_line_builds_checks_and_scores_a_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "answers.json"
    run.write_text(json.dumps(RECORDS), encoding="utf-8")
    monkeypatch.setattr(answer, "understand", lambda q, chat: (False, [Part(q)]))

    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=reply({"parts": [1, 0]}),
                              request=httpx.Request("POST", url))  # fmt: skip

    monkeypatch.setattr(llm.CLIENT, "post", post)
    items, results = tmp_path / "items.json", tmp_path / "c3.json"
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"q1": [1, 0]}), encoding="utf-8")

    assert cli.main(["relevance-items", str(run), "--out", str(items)]) == 0
    assert "1 answers, 2 claims" in capsys.readouterr().out
    assert cli.main(["relevance-check", str(items), "--candidate", "c3",
                     "--out", str(results)]) == 0  # fmt: skip
    assert "1 items checked by c3" in capsys.readouterr().out
    assert cli.main(["relevance-score", str(labels), str(results)]) == 0
    assert json.loads(capsys.readouterr().out)["rightly_removed"] == 1

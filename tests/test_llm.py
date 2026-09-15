import json
from typing import Any

import httpx
import pytest

from limespec import config, llm

SCHEMA = {"type": "object"}


def chat_reply(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    message = {"content": content}
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def test_chat_sends_the_fixed_request_and_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.update(url=url, **kwargs)
        body = chat_reply(json.dumps({"claims": []}))
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    assert llm.chat("system text", "user text", SCHEMA) == {"claims": []}
    payload = sent["json"]
    assert sent["url"] == config.CHAT_URL
    assert payload["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert (payload["temperature"], payload["seed"]) == (0.0, 42)
    assert payload["max_tokens"] == config.MAX_ANSWER_TOKENS
    assert "model" not in payload


@pytest.mark.parametrize("content", ['{"claims": [{"evid', '{"claims": []}'])
def test_a_cut_off_reply_is_a_clear_error_even_if_it_is_valid_json(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        body = chat_reply(content, finish_reason="length")
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="did not finish"):
        llm.chat("s", "u", SCHEMA)


def test_a_finished_reply_that_is_not_json_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        body = chat_reply("not json")
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="not valid JSON"):
        llm.chat("s", "u", SCHEMA)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"finish_reason": "stop", "message": {}}]},
    ],
)
def test_a_malformed_server_response_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        if body is None:
            return httpx.Response(
                200, text="not json", request=httpx.Request("POST", url)
            )
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="malformed response"):
        llm.chat("s", "u", SCHEMA)


def test_a_non_text_reply_content_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        body = chat_reply("")
        body["choices"][0]["message"]["content"] = None
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="not valid JSON"):
        llm.chat("s", "u", SCHEMA)


def test_an_unavailable_generation_model_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match=config.CHAT_URL):
        llm.chat("s", "u", SCHEMA)


def test_embed_returns_vectors_in_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        data = [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]
        return httpx.Response(
            200, json={"data": data}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)

    assert llm.embed(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_rerank_sends_the_query_and_documents_and_returns_scores_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.update(url=url, **kwargs)
        results = [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": -2.5},
        ]
        return httpx.Response(
            200, json={"results": results}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)

    assert llm.rerank("question", ["first", "second"]) == [-2.5, 0.9]
    assert sent["url"] == config.RERANK_URL
    assert sent["json"] == {"query": "question", "documents": ["first", "second"]}


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"data": {}},
        {"data": [None]},
        {"data": [{}]},
        {"data": [{"index": "0", "embedding": [1.0]}]},
        {"data": [{"index": False, "embedding": [1.0]}]},
        {"data": []},
        {"data": [{"index": 1, "embedding": [1.0]}]},
        {"data": [{"index": 0}, {"index": 1, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": [1.0]}] * 2},
        {
            "data": [
                {"index": 0, "embedding": [1.0]},
                {"index": 1, "embedding": [1.0, 0.0]},
            ]
        },
        *[
            {
                "data": [
                    {"index": 0, "embedding": vector},
                    {"index": 1, "embedding": [1.0]},
                ]
            }
            for vector in (None, [], "1.0", [True], ["nan"], [float("inf")])
        ],
    ],
)
def test_malformed_embeddings_fail_before_retrieval_or_indexing(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            text="not json" if body is None else json.dumps(body),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="embedding.*malformed response"):
        llm.embed(["first passage", "second passage"])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"results": {}},
        {"results": [{"index": 0}]},
        {"results": [{"index": "0", "relevance_score": 1}]},
        {"results": [{"relevance_score": 1}]},
    ],
)
def test_a_malformed_rerank_response_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="malformed response"):
        llm.rerank("question", ["first"])


def test_a_rerank_response_missing_a_passage_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        results = [{"index": 0, "relevance_score": 1.0}]
        return httpx.Response(
            200, json={"results": results}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="did not score every passage"):
        llm.rerank("question", ["first", "second"])


@pytest.mark.parametrize(
    "results",
    [
        [
            {"index": 0, "relevance_score": 1.0},
            {"index": 0, "relevance_score": 0.5},
        ],
        [
            {"index": 0, "relevance_score": 1.0},
            {"index": 2, "relevance_score": 0.5},
        ],
    ],
)
def test_rerank_requires_each_passage_index_exactly_once(
    monkeypatch: pytest.MonkeyPatch, results: list[dict[str, float | int]]
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200, json={"results": results}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="did not score every passage"):
        llm.rerank("question", ["first", "second"])


def test_a_non_finite_rerank_score_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"index": 0, "relevance_score": "nan"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match="malformed response"):
        llm.rerank("question", ["first"])


def test_unreachable_reranking_server_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match=config.RERANK_URL):
        llm.rerank("question", ["first"])


def test_unreachable_embedding_server_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(llm.ModelServerError, match=config.EMBEDDING_URL):
        llm.embed(["question"])

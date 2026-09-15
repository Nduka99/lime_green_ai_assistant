"""A small client for the llama.cpp servers' OpenAI-compatible API."""

import json
import math
from typing import Any

import httpx

from limespec import config


class ModelServerError(RuntimeError):
    """A model server could not be reached or returned an unusable response."""


def embed(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per text, in the same order."""
    try:
        response = httpx.post(
            config.EMBEDDING_URL,
            json={"input": texts, "model": config.EMBEDDING_MODEL},
            timeout=config.SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ModelServerError(
            f"embedding server at {config.EMBEDDING_URL} failed: {error}"
        ) from error
    try:
        items = response.json()["data"]
        if not isinstance(items, list):
            raise TypeError
        indices = [item["index"] for item in items]
        if any(type(index) is not int for index in indices):
            raise TypeError
        if sorted(indices) != list(range(len(texts))):
            raise ValueError
        vectors = [item["embedding"] for item in items]
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise TypeError
            if any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in vector
            ):
                raise ValueError
        if len({len(vector) for vector in vectors}) > 1:
            raise ValueError
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        raise ModelServerError(
            "the embedding server returned a malformed response"
        ) from error
    # Match by index, never response order, so vectors stay attached to their text.
    return [vector for _, vector in sorted(zip(indices, vectors, strict=True))]


def rerank(query: str, documents: list[str]) -> list[float]:
    """Return one relevance score per document, in the same order (higher is better).

    The reranker is a cross-encoder: it reads the question together with each
    document, so it can judge relevance that shares no words with the question.
    """
    try:
        response = httpx.post(
            config.RERANK_URL,
            json={"query": query, "documents": documents},
            timeout=config.SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ModelServerError(
            f"reranking server at {config.RERANK_URL} failed: {error}"
        ) from error
    try:
        results = response.json()["results"]
        if not isinstance(results, list):
            raise TypeError
        indices = [item["index"] for item in results]
        if any(type(index) is not int for index in indices):
            raise TypeError
        scores = [float(item["relevance_score"]) for item in results]
        if any(not math.isfinite(score) for score in scores):
            raise ValueError
    except (ValueError, KeyError, TypeError) as error:
        raise ModelServerError(
            "the reranking server returned a malformed response"
        ) from error
    if len(scores) != len(documents) or sorted(indices) != list(range(len(documents))):
        raise ModelServerError("the reranking server did not score every passage")
    return [score for _, score in sorted(zip(indices, scores, strict=True))]


def chat(system: str, user: str, schema: dict[str, Any]) -> object:
    """Send one chat request whose reply must follow `schema`; return the parsed JSON.

    The request names no model: the server answers with whichever GGUF it has
    loaded, which lets the same client work with any model.
    """
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.TEMPERATURE,
        "seed": config.SEED,
        "max_tokens": config.MAX_ANSWER_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema},
        },
        # Reasoning is discarded, so it is switched off at the chat template:
        # a reasoning budget alone does not stop Qwen3.x from thinking.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        response = httpx.post(
            config.CHAT_URL, json=payload, timeout=config.CHAT_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ModelServerError(
            f"generation server at {config.CHAT_URL} failed: {error}"
        ) from error
    try:
        choice = response.json()["choices"][0]
        finish = choice["finish_reason"]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ModelServerError(
            "the generation server returned a malformed response"
        ) from error
    # A reply cut off at max_tokens can still happen to be valid JSON, so only a
    # reply the model finished itself is used.
    if finish != "stop":
        raise ModelServerError(f"the model's reply did not finish ({finish})")
    try:
        reply: object = json.loads(content)
    except (json.JSONDecodeError, TypeError) as error:
        raise ModelServerError("the model's reply is not valid JSON") from error
    return reply

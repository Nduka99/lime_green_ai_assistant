"""E8's specialist arm: OCC-RAG, a small model trained to judge whether its sources
answer a question, as a per-part answerability gate.

OCC-RAG reads a question wrapped in `<|query_start|>…<|query_end|>` and numbered sources
wrapped in `<|source_start|><|source_id|>N …<|source_end|>` (its model card), writes
its analysis, then `<|status_start|>`, a line break and ANSWERABLE or UNANSWERABLE,
then a short answer. The score of a (question, sources) pair is ANSWERABLE's share of
the two words' first tokens ("ANS", "UN") at the status. llama-server writes special
tokens as empty text, so the status is found by its token id. A claim scores its best
part, as E5's and E7's detectors did.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from evaluation.graders import Send
from limespec.models import Passage

STATUS_START = 151680  # <|status_start|> in OCC-RAG's vocabulary (its GGUF token list)
MAX_TOKENS = 1536  # the analysis and answer; a reply cut before the status scores 0.5


def prompt(question: str, sources: Sequence[str]) -> str:
    """The model's own input format."""
    lines = [f"<|query_start|>{question}<|query_end|>"]
    for number, text in enumerate(sources, 1):
        lines.append(f"<|source_start|><|source_id|>{number} {text}<|source_end|>")
    return "\n".join(lines) + "\n"


def body(question: str, sources: Sequence[str]) -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": prompt(question, sources)}],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "logprobs": True,
        "top_logprobs": 10,
    }


def status_share(candidates: Sequence[Mapping[str, Any]]) -> float:
    """ANSWERABLE's share at the status's first token. A reading missing from the
    listed alternatives gets the lowest listed log-probability, an upper bound on its
    own, so a confident status still scores short of 0 or 1."""
    lowest = min(candidate["logprob"] for candidate in candidates)
    weights = {"ANS": lowest, "UN": lowest}
    for candidate in candidates:
        word = candidate["token"].strip().upper()
        for start in weights:
            if word.startswith(start):
                weights[start] = max(weights[start], candidate["logprob"])
                break
    yes, no = math.exp(weights["ANS"]), math.exp(weights["UN"])
    return yes / (yes + no)


def answerable(generated: Sequence[Mapping[str, Any]]) -> float:
    """The status's share of ANSWERABLE, or 0.5 when the reply has no status."""
    ids = [position["id"] for position in generated]
    if STATUS_START not in ids:
        return 0.5
    for position in generated[ids.index(STATUS_START) + 1 :]:
        if position["token"].strip():
            return status_share(position["top_logprobs"])
    return 0.5


def score(question: str, sources: Sequence[str], send: Send) -> float:
    reply = send(body(question, sources))
    return answerable(reply["choices"][0]["logprobs"]["content"])


def by_parts(
    found: Sequence[Mapping[str, Any]],
    sources: Mapping[str, Sequence[str]],
    send: Send,
) -> dict[str, float]:
    """Each item's score: its best part's, with the item's sources."""
    scores = {}
    for item in found:
        texts = sources[item["id"]]
        scores[item["id"]] = max(score(part, texts, send) for part in item["parts"])
    return scores


def as_text(title: str, heading: str, text: str) -> str:
    """A source as the text OCC-RAG reads: where it stands, then what it says."""
    where = f"{title} › {heading}" if heading and heading != title else title
    return f"{where}: {text}"


def quoted(sources: Mapping[str, Sequence[Sequence[str]]]) -> dict[str, list[str]]:
    """Each claim's cited (title, heading, quote) sources as texts."""
    texts = {}
    for key, cited in sources.items():
        texts[key] = [as_text(*source) for source in cited]
    return texts


def whole(
    found: Sequence[Mapping[str, Any]], passages: Mapping[str, Passage]
) -> dict[str, list[str]]:
    """Each near-miss question's whole passage, as the generator reads it."""
    texts = {}
    for item in found:
        passage = passages[item["case"]]
        texts[item["id"]] = [as_text(passage.title, passage.heading, passage.text)]
    return texts

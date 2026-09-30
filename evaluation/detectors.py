"""Claim detectors that run on the CPU (E5 stage C, candidates c, d and e).

Term coverage (d) needs no model: the share of a question part's word weight found in
a claim's quotes, words weighted by inverse document frequency over the index. The
combination (e) averages detectors' percentile ranks.

The support checker (c, FactCG-DeBERTa-v3-Large) gives every item of the claim
benchmark (`evaluation.claims`) the probability that the quotes it cites, joined,
support it: the instruction template and class 1 ("supported") of the model's
reference code (derenlei/FactCG, `factcg/inference.py` and `utils.py`). The quotes are
far below the reference's 550-token chunk, so they are not chunked. The model loads
from its folder in `models/`, never from the network.
"""

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from evaluation.claims import Item

WORD = re.compile(r"[a-z0-9]+")

SUPPORT_TEMPLATE = (
    "{text_a}\n\nChoose your answer: based on the paragraph above can we conclude that"
    ' "{text_b}"?\n\nOPTIONS:\n- Yes\n- No\nI think the answer is '
)
BATCH = 8
Predict = Callable[[list[str]], list[float]]


def support_text(item: Item) -> str:
    return SUPPORT_TEMPLATE.format(
        text_a="\n".join(item["quotes"]), text_b=item["claim"]
    )


def by_support(found: Sequence[Item], predict: Predict) -> dict[str, float]:
    """Candidate (c): the probability that a claim's own quotes support it."""
    scores: dict[str, float] = {}
    for start in range(0, len(found), BATCH):
        batch = found[start : start + BATCH]
        texts = [support_text(item) for item in batch]
        for item, value in zip(batch, predict(texts), strict=True):
            scores[item["id"]] = value
    return scores


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def rarity(texts: Sequence[str]) -> dict[str, float]:
    """Inverse document frequency of every word of `texts`."""
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(words(text))
    return {word: math.log(len(texts) / count) for word, count in counts.items()}


def by_terms(found: Sequence[Item], weights: Mapping[str, float]) -> dict[str, float]:
    """Candidate (d): for a claim's best part, the share of the part's word weight
    that its quotes contain. A word the index never holds gets the highest weight."""
    unseen = max(weights.values(), default=1.0)
    scores = {}
    for item in found:
        quoted = words(" ".join(item["quotes"]))
        best = 0.0
        for part in item["parts"]:
            asked = {word: weights.get(word, unseen) for word in words(part)}
            total = sum(asked.values())
            if total:
                best = max(best, sum(asked[w] for w in asked if w in quoted) / total)
        scores[item["id"]] = best
    return scores


def ranks(scores: Mapping[str, float]) -> dict[str, float]:
    """Each id's percentile rank (0 to 1) among the scores; ties share their mean."""
    ordered = sorted(scores.values())
    places: dict[float, list[int]] = {}
    for place, value in enumerate(ordered):
        places.setdefault(value, []).append(place)
    last = max(len(ordered) - 1, 1)
    return {key: sum(places[v]) / len(places[v]) / last for key, v in scores.items()}


def combined(detectors: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Candidate (e): the mean of the detectors' percentile ranks."""
    ranked = [ranks(scores) for scores in detectors]
    return {key: sum(r[key] for r in ranked) / len(ranked) for key in ranked[0]}


def support_model(folder: Path) -> Predict:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(folder)
    model = AutoModelForSequenceClassification.from_pretrained(folder).eval()

    def predict(texts: list[str]) -> list[float]:
        batch = tokenizer(
            texts,
            truncation=True,
            max_length=2048,
            padding="longest",
            return_tensors="pt",
        )
        with torch.no_grad():
            probabilities = torch.softmax(model(**batch).logits, dim=-1)
        return [float(value) for value in probabilities[:, 1]]

    return predict

"""Claim detectors on the CPU (E5 stage C). Every claim, quote and score here is
invented; the support model is a stand-in, never the real weights."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import torch
import transformers

from evaluation import __main__ as cli
from evaluation import detectors
from limespec import assistant, store

ITEMS = [
    {"id": "a", "claim": "Duro has no cement.", "quotes": ["Duro contains no cement."],
     "parts": ["does Duro contain cement", "Duro price"]},
    {"id": "b", "claim": "Solo is for walls.", "quotes": ["Solo suits walls.", "Dry."],
     "parts": ["is Solo for floors"]},
]  # fmt: skip


def test_the_support_text_is_the_reference_template_with_quotes_joined() -> None:
    text = detectors.support_text(ITEMS[1])

    assert text.startswith("Solo suits walls.\nDry.\n\nChoose your answer:")
    assert 'conclude that "Solo is for walls."?' in text
    assert text.endswith("I think the answer is ")


def test_support_scores_every_claim_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detectors, "BATCH", 1)
    seen: list[list[str]] = []

    def predict(texts: list[str]) -> list[float]:
        seen.append(texts)
        return [0.25]

    assert detectors.by_support(ITEMS, predict) == {"a": 0.25, "b": 0.25}
    assert len(seen) == 2


def test_term_coverage_weights_rare_words_and_keeps_the_best_part() -> None:
    weights = detectors.rarity(["duro contains", "duro solo", "cement"])

    assert weights["duro"] == pytest.approx(0.405, abs=0.001)
    scores = detectors.by_terms(ITEMS, weights)
    # "does" and "contain" are unseen, so weigh most; "duro" and "cement" are quoted.
    assert 0 < scores["a"] < 1
    assert scores["b"] == pytest.approx(
        weights["solo"] / (weights["solo"] + 3 * max(weights.values()))
    )
    assert detectors.by_terms([{**ITEMS[0], "parts": ["?"]}], weights) == {"a": 0.0}


def test_ranks_share_ties_and_the_combination_averages_them() -> None:
    assert detectors.ranks({"a": 1.0, "b": 1.0, "c": 5.0}) == {
        "a": 0.25,
        "b": 0.25,
        "c": 1.0,
    }
    assert detectors.ranks({"a": 3.0}) == {"a": 0.0}
    first = {"a": 1.0, "b": 2.0}
    second = {"a": 9.0, "b": 0.0}
    assert detectors.combined([first, second]) == {"a": 0.5, "b": 0.5}


class Model:
    def eval(self) -> "Model":
        return self

    def __call__(self, **batch: Any) -> Any:
        rows = len(batch["input_ids"])
        return type("Output", (), {"logits": torch.tensor([[0.0, 0.0]] * rows)})


def test_the_support_model_reads_class_one_as_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tokenizer(texts: list[str], **options: Any) -> dict[str, Any]:
        assert options["truncation"] is True and options["max_length"] == 2048
        return {"input_ids": torch.zeros((len(texts), 3), dtype=torch.long)}

    monkeypatch.setattr(
        transformers.AutoTokenizer, "from_pretrained", lambda folder: tokenizer
    )
    monkeypatch.setattr(
        transformers.AutoModelForSequenceClassification,
        "from_pretrained",
        lambda folder: Model(),
    )

    predict = detectors.support_model(Path("models/any"))

    assert predict(["one", "two"]) == [0.5, 0.5]


def test_the_answer_margin_is_the_best_span_inside_the_text_over_no_answer() -> None:
    start = [1.0, 0.0, 5.0, 0.0, 9.0]
    end = [1.0, 0.0, 0.0, 4.0, 0.0]
    inside = [False, False, True, True, False]  # the question and padding are outside

    # Best span inside: tokens 2 to 3 (5 + 4); no answer scores 1 + 1.
    assert detectors.answer_margin(start, end, inside) == 7.0
    assert detectors.answer_margin(start, end, [False] * 5) == float("-inf")


def test_the_reader_scores_a_claim_by_its_best_part_over_quotes_or_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detectors, "BATCH", 1)
    asked: list[tuple[str, str]] = []

    def read(questions: list[str], texts: list[str]) -> list[float]:
        asked.extend(zip(questions, texts, strict=True))
        return [2.0 if "cement" in questions[0] else -3.0]

    assert detectors.by_reader(ITEMS, read, "quotes") == {"a": 2.0, "b": -3.0}
    assert asked[0] == ("does Duro contain cement", "Duro contains no cement.")
    assert asked[2] == ("is Solo for floors", "Solo suits walls.\nDry.")
    asked.clear()
    detectors.by_reader(ITEMS, read, "claim")
    assert asked[0] == ("does Duro contain cement", "Duro has no cement.")


class Batch(dict[str, Any]):
    def sequence_ids(self, row: int) -> list[int | None]:
        return [None, 0, None, 1, 1, None]


class Reader:
    def eval(self) -> "Reader":
        return self

    def __call__(self, **batch: Any) -> Any:
        logits = torch.tensor([[2.0, 0.0, 0.0, 3.0, 1.0, 9.0]])
        return type("Output", (), {"start_logits": logits, "end_logits": logits})


def test_the_reader_model_reads_spans_of_the_second_text_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tokenizer(questions: list[str], texts: list[str], **options: Any) -> Batch:
        assert options["truncation"] == "only_second" and options["max_length"] == 512
        return Batch(input_ids=torch.zeros((1, 6), dtype=torch.long))

    monkeypatch.setattr(
        transformers.AutoTokenizer, "from_pretrained", lambda folder: tokenizer
    )
    monkeypatch.setattr(
        transformers.AutoModelForQuestionAnswering,
        "from_pretrained",
        lambda folder: Reader(),
    )

    read = detectors.reader_model(Path("models/any"))

    # Inside: tokens 3 and 4; best span 3 to 3 (3 + 3); no answer 2 + 2.
    assert read(["q"], ["t"]) == [2.0]


def test_the_command_line_scores_terms_combines_and_checks_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    items = tmp_path / "items.json"
    items.write_text(json.dumps(ITEMS), encoding="utf-8")

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "searchable_texts", lambda conn, version: ["duro", "x"])
    monkeypatch.setattr(
        detectors, "support_model", lambda folder: lambda t: [0.9] * len(t)
    )
    monkeypatch.setattr(
        detectors, "reader_model", lambda folder: lambda q, t: [1.5] * len(q)
    )
    read = tmp_path / "read.json"
    assert (
        cli.main(
            ["claim-reader", str(items), "--model", "m", "--text", "claim"]
            + ["--out", str(read)]
        )
        == 0
    )
    assert json.loads(read.read_text()) == {"a": 1.5, "b": 1.5}
    terms = tmp_path / "terms.json"
    support = tmp_path / "support.json"
    mixed = tmp_path / "mixed.json"

    assert (
        cli.main(["claim-terms", str(items), "--version", "12", "--out", str(terms)])
        == 0
    )
    assert (
        cli.main(["claim-support", str(items), "--model", "m", "--out", str(support)])
        == 0
    )
    assert (
        cli.main(["claim-combine", str(terms), str(support), "--out", str(mixed)]) == 0
    )

    assert json.loads(support.read_text()) == {"a": 0.9, "b": 0.9}
    assert set(json.loads(mixed.read_text())) == {"a", "b"}
    assert capsys.readouterr().out.count("2 claims scored") == 4

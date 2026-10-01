"""X43 B3's picture ranking (arms T+S). No model is loaded: SigLIP2 is replaced."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import torch
import transformers
from PIL import Image

from evaluation import __main__ as cli
from evaluation import sets, visual
from limespec import assistant, config, store
from limespec.models import Passage


def passage(number: int, image: str = "") -> Passage:
    return Passage(number, "u", "T", "", "", "", image=image)


class Model:
    def eval(self) -> "Model":
        return self

    def get_image_features(self, **batch: Any) -> Any:
        rows = len(batch["pixel_values"])
        return type("Output", (), {"pooler_output": torch.tensor([[3.0, 4.0]] * rows)})

    def get_text_features(self, **batch: Any) -> Any:
        rows = len(batch["input_ids"])
        return type("Output", (), {"pooler_output": torch.tensor([[0.0, 2.0]] * rows)})


def test_the_model_gives_unit_vectors_and_reads_text_lowercased(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Any] = []

    def processor(**options: Any) -> dict[str, Any]:
        asked.append(options)
        if "images" in options:
            return {"pixel_values": [0] * len(options["images"])}
        return {"input_ids": [0] * len(options["text"])}

    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", lambda f: Model())
    monkeypatch.setattr(
        transformers.AutoProcessor, "from_pretrained", lambda f: processor
    )
    Image.new("RGB", (4, 4), "green").save(tmp_path / "a.png")

    pictures, texts = visual.siglip_model(tmp_path)

    assert pictures([tmp_path / "a.png"]) == [[0.6000000238418579, 0.800000011920929]]
    assert texts(["Show Me Duro"]) == [[0.0, 1.0]]
    assert asked[1]["text"] == ["show me duro"]
    assert (asked[1]["padding"], asked[1]["max_length"]) == ("max_length", 64)


def test_vectors_resume_and_pictures_rank_by_cosine(tmp_path: Path) -> None:
    embedded: list[list[str]] = []

    def embed(paths: list[Path]) -> list[list[float]]:
        embedded.append([path.stem for path in paths])
        return [[1.0, 0.0] for _ in paths]

    vectors = visual.picture_vectors(["a", "b"], tmp_path, embed, {"a": [0.0, 1.0]})

    assert vectors == {"a": [0.0, 1.0], "b": [1.0, 0.0]} and embedded == [["b"]]
    assert visual.picture_ranking([0.0, 1.0], vectors, {"a": 7, "b": 3}) == [7, 3]
    assert visual.picture_ranking([0.0, 0.0], vectors, {"a": 7, "b": 3}) == [3, 7]


def test_the_quota_keeps_the_reranked_top_and_adds_new_pictures() -> None:
    ranked = [passage(n) for n in range(1, 10)]
    pictures = [passage(2, "x"), passage(20, "y"), passage(21, "z")]

    found = visual.with_quota(ranked, pictures)

    assert [p.id for p in found] == [1, 2, 3, 4, 5, 6, 20, 21, 7, 8, 9]


@pytest.mark.parametrize("arm", ["pool", "quota"])
def test_the_command_line_embeds_pictures_and_scores_each_arm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arm: str,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    places = [{"id": "b"}, {"id": "b"}, {"id": "c"}]
    (images / "places.json").write_text(json.dumps(places), encoding="utf-8")
    monkeypatch.setattr(config, "IMAGES", images)
    monkeypatch.setattr(
        visual,
        "siglip_model",
        lambda folder: (
            lambda paths: [[1.0, 0.0] for _ in paths],
            lambda texts: [[1.0, 0.0] for _ in texts],
        ),
    )
    vectors = tmp_path / "vectors.json"
    assert cli.main(["image-vectors", "--out", str(vectors)]) == 0
    assert "2 picture vectors" in capsys.readouterr().out

    folder = tmp_path / "eval" / "image-facts"
    folder.mkdir(parents=True)
    item = {"id": "q", "set": "image-facts", "cluster": "q", "kind": "site",
            "question": "Show me York", "accepted": ["b"]}  # fmt: skip
    (folder / "questions.json").write_text(json.dumps({"questions": [item]}))
    registry = tmp_path / "sets.json"
    sets.register("image-facts", "", tmp_path / "eval", registry)

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    fused: list[Any] = []

    def search(
        conn: Any, version: int, question: str, *models: Any, **opts: Any
    ) -> Any:
        fused.append(opts.get("also"))
        return [passage(1)] * 8  # text only: the quota adds the pictures

    def pooled(
        conn: Any, version: int, question: str, *models: Any, **opts: Any
    ) -> Any:
        fused.append(opts.get("also"))
        return [passage(5, "b")]

    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "search", pooled if arm == "pool" else search)
    monkeypatch.setattr(store, "picture_passages", lambda conn, v: {"b": 5, "c": 6})
    monkeypatch.setattr(
        store, "load_passages", lambda conn, ids: [passage(n, "b") for n in ids]
    )
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]
    out = tmp_path / "run.json"
    command = ["image-retrieval", "--version", "21", "--out", str(out)]

    assert cli.main([*common, *command, "--visual", str(vectors), "--arm", arm]) == 0

    assert "Success@8 1.000" in capsys.readouterr().out
    assert fused == ([[[5, 6]]] if arm == "pool" else [None])  # one ranking more
    assert json.loads(out.read_text())["arm"] == f"T+S {arm}"

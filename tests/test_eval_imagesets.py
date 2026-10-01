"""X43's image sets: candidates drawn for the OCR truth. Invented records."""

import json
from io import BytesIO
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

from evaluation import __main__ as cli
from evaluation import imagesets, sets
from limespec import acquire, config

SITE = "https://www.lime-green.co.uk/"


def record(
    name: str, sha: str, kind: str = "image", form: str = "image/webp"
) -> dict[str, str]:
    return {"url": SITE + name, "kind": kind, "sha256": sha, "content_type": form}


RECORDS = [
    record("images/Products/duro.webp", "a" * 64),
    record("images/Products/solo.webp", "b" * 64),
    record("images/Products/solo-copy.webp", "b" * 64),  # the same file again
    record("images/Layout/logo.svg", "c" * 64, form="image/svg+xml"),
    record("images/ImageLib/wall.jpg", "d" * 64),
    record("Documents/duro.pdf", "e" * 64, kind="document", form="application/pdf"),
]
READING = {
    "sha256": "f" * 64,
    "urls": [SITE + "Documents/duro-tds.pdf"],
    "elements": [
        {"kind": "figure", "page": 1, "bbox": [0, 0, 100, 100]},
        {"kind": "figure", "page": 1, "bbox": [0, 0, 50, 100]},  # too narrow
        {"kind": "figure", "page": 1, "bbox": []},
        {"kind": "paragraph", "page": 1, "bbox": [0, 0, 100, 100]},
    ],
}


def test_candidates_are_drawn_in_turn_from_each_group() -> None:
    assert imagesets.folder(SITE + "images/Products/duro.webp") == "images/Products"
    assert imagesets.interleaved({"b": [3], "a": [1, 2]}, seed=1) in (
        [1, 3, 2],
        [2, 3, 1],
    )

    site = imagesets.site_candidates(RECORDS, seed=1)
    figures = imagesets.figure_candidates([READING], {}, seed=1)

    assert sorted(c["sha256"][0] for c in site) == ["a", "b", "d"]
    assert site[0]["group"] != site[1]["group"]  # one folder, then the other
    assert [(c["id"], c["group"]) for c in figures] == [
        ("figure/" + "f" * 12 + "/0", "pdf:other")
    ]


def test_the_command_line_writes_each_candidate_as_its_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "files"
    store.mkdir()
    picture = BytesIO()
    Image.new("RGB", (40, 20), "green").save(picture, format="WEBP")
    for sha in "abd":
        (store / (sha * 64)).write_bytes(picture.getvalue())
    document = pypdfium2.PdfDocument.new()
    document.new_page(200, 200)
    document.save(str(store / ("f" * 64)))
    document.close()
    readings = tmp_path / "elements"
    readings.mkdir()
    (readings / "f.json").write_text(json.dumps(READING), encoding="utf-8")
    (readings / "report.json").write_text("{}", encoding="utf-8")
    catalogue = tmp_path / "catalogue.json"
    entry = {"url": SITE + "Documents/duro-tds.pdf", "format": "pdf:technical"}
    catalogue.write_text(json.dumps([entry]), encoding="utf-8")
    monkeypatch.setattr(config, "READINGS", readings)
    monkeypatch.setattr(acquire, "read_manifest", lambda: RECORDS)
    monkeypatch.setattr(acquire, "store_path", lambda sha: store / sha)
    out = tmp_path / "candidates"

    command = ["image-candidates", "--seed", "43", "--catalogue", str(catalogue)]
    assert cli.main([*command, "--count", "2", "--out", str(out)]) == 0

    kept = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    assert len(kept) == 3 and kept[-1]["group"] == "pdf:technical"
    assert all((out / candidate["png"]).exists() for candidate in kept)
    assert "3 candidates" in capsys.readouterr().out


def test_ocr_is_scored_by_words_against_the_transcription() -> None:
    images = [
        {"id": "site/a", "text": "Solo OneCoat Plaster 25kg"},
        {"id": "figure/b/1", "text": "Fixing: 40mm"},
    ]
    readings = {"site/a": r"SOLO One-Coat Plaster $25\mathrm{kg}$", "figure/b/1": ""}

    found = imagesets.ocr_score(images, readings)

    assert found["images"]["site/a"] == {"words": 4, "read": 5, "right": 3}
    assert found["rates"]["all"]["recall"] == 3 / 6
    assert found["rates"]["figure"] == {"recall": 0.0, "precision": 0.0}


def test_the_command_line_reads_each_registered_image_once_and_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from limespec import tables

    folder = tmp_path / "eval" / "image-text"
    (folder / "images").mkdir(parents=True)
    Image.new("RGB", (20, 10), "white").save(folder / "images" / "a.png")
    truth = {"images": [{"id": "site/a", "png": "a.png", "text": "lime green"}]}
    (folder / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    registry = tmp_path / "sets.json"
    sets.register("image-text", "", tmp_path / "eval", registry)
    calls = []

    def recognise(image: object, url: str, prompt: str) -> str:
        calls.append((url, prompt))
        return "lime green"

    monkeypatch.setattr(tables, "recognise", recognise)
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]
    out = tmp_path / "ocr.json"
    command = [*common, "image-ocr", "--url", "http://vlm", "--out", str(out)]

    assert cli.main(command) == 0
    assert cli.main(command) == 0  # the saved reading is kept, not asked again
    assert calls == [("http://vlm", "Text Recognition:")]
    assert cli.main([*common, "image-ocr-score", str(out)]) == 0
    assert "all: recall 1.000, precision 1.000" in capsys.readouterr().out

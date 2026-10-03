"""X43 A3a: Word readings scored against judged pages. Invented truth and readings."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import docxpages, sets
from limespec import acquire, office, pdf
from limespec.elements import Element

PAGE = {
    "sha256": "d1",
    "page": 1,
    "headings": ["EC Declaration of Performance"],
    "lines": ["EC Declaration of Performance", "Reaction to fire:", "Class A1", "13"],
    "pairs": [["Reaction to fire:", "Class A1"]],
    "tables": [{"grid": [["Water absorption", "1.65"]], "header_rows": 0}],
    "images": ["CE mark", "signature"],
}
READING = [
    Element(1, "heading", "EC Declaration of Performance"),
    Element(1, "paragraph", "Reaction to fire: Class A1"),
    Element(
        1, "table", "Water absorption | 1.65", grid=(("Water absorption", "1.65"),)
    ),
    Element(1, "figure", ""),
]


def test_a_reading_is_scored_against_the_judged_pages() -> None:
    found = docxpages.scores([PAGE], {"d1": READING})

    counts = found["documents"]["d1"]
    assert counts["pairs"] == (1, 1) and counts["grid"] == (1, 1)
    assert counts["images"] == (1, 2) and counts["headings"] == (1, 1)
    assert counts["numbers"] == (1, 2)  # "1" of Class A1 is read, "13" is not
    assert found["passed"]["images"] is False


def test_the_command_line_scores_each_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "eval" / "docx-pages"
    folder.mkdir(parents=True)
    (folder / "truth.json").write_text(json.dumps({"pages": [PAGE]}), encoding="utf-8")
    registry = tmp_path / "sets.json"
    sets.register("docx-pages", "", tmp_path / "eval", registry)
    monkeypatch.setattr(acquire, "store_path", lambda sha: tmp_path / sha)
    monkeypatch.setattr(office, "read_docx", lambda path: READING)
    monkeypatch.setattr(office, "render_pdf", lambda path, out: out / "d1.pdf")
    asked: dict[str, Any] = {}

    def read_pdf(path: Path, vlm: str) -> list[Element]:
        asked["vlm"] = vlm
        return READING

    monkeypatch.setattr(pdf, "read_pdf", read_pdf)
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]
    out = tmp_path / "scores"

    for arm in ("docling-word", "rendered-pdf", "rendered-pdf-lines"):
        command = [*common, "docx-score", arm, "--vlm", "http://vlm", "--out", str(out)]
        assert cli.main(command) == 0
        saved = json.loads((out / f"{arm}.json").read_text(encoding="utf-8"))
        assert saved["readings"]["d1"][0]["kind"] == "heading"
    assert asked["vlm"] == "http://vlm"
    assert '"images": false' in capsys.readouterr().out


def test_saved_x8_readings_are_rescored_with_side_by_side_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "eval" / "x8-pages"
    folder.mkdir(parents=True)
    page = {
        "number": 1,
        "tables": [],
        "pairs": [["Declared unit", "1 kg"]],
        "sentences": ["Declared unit 1 kg"],
    }
    (folder / "truth.json").write_text(json.dumps({"pages": [page]}), encoding="utf-8")
    registry = tmp_path / "sets.json"
    sets.register("x8-pages", "", tmp_path / "eval", registry)
    row = {"page": 1, "kind": "paragraph", "section": [], "table": None, "row": None}
    reading = [
        row
        | {"text": "Declared unit", "bbox": [10, 10, 80, 20], "cells": [], "grid": []},
        row | {"text": "Other text", "bbox": [10, 40, 80, 50], "cells": [], "grid": []},
        row | {"text": "1 kg", "bbox": [200, 10, 230, 20], "cells": [], "grid": []},
        row | {"text": "", "bbox": None, "cells": [], "grid": [], "kind": "table"},
    ]
    run = tmp_path / "parsed.json"
    run.write_text(json.dumps({"1": {"pypdf": ["Declared unit 1 kg"], "a": reading}}))
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]

    assert cli.main([*common, "layout-check", "x8-pages", str(run), "--arm", "a"]) == 0
    printed = capsys.readouterr().out
    assert '"pairs": 0.0' in printed and '"pairs": 1.0' in printed
    assert "falls: none" in printed

    # A sentence read across the two blocks is broken by the joining: it falls.
    found = docxpages.layout_check(
        [page | {"sentences": ["Declared unit Other text"]}],
        json.loads(run.read_text()),
        "a",
    )
    assert found["falls"] == ["page 1 sentences"]

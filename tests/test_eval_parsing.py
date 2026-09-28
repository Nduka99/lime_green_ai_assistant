"""Scoring PDF parsers against ground truth (X8). Every page and text is invented."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import parsing, sets
from limespec import pdf, tables
from limespec.elements import Element

TABLE = {"header": ["Property", "Class i", "Class ii"], "rows": [["Fire", "A1", "A2"]]}


def test_a_cell_is_found_by_its_row_label_column_header_and_value() -> None:
    rows: parsing.Rows = [
        (),
        (("Property", "Fire"), ("Performance › Class i", "A1"),
         ("Performance › Class ii", "A 2")),
    ]  # fmt: skip
    wrong: parsing.Rows = [
        (("Property", "Fire"), ("Class ii", "A1"), ("Class i", "A2"))
    ]

    assert parsing.table_cells([TABLE], rows) == (2, 2, [1.0])
    assert parsing.table_cells([TABLE], wrong) == (0, 2, [0.0])
    any_column = {"header": ["", ""], "rows": [["Fire", "A1"]]}
    assert parsing.table_cells([any_column], wrong) == (1, 1, [1.0])
    empty = {"header": ["", ""], "rows": [["Notes", ""]]}
    assert parsing.table_cells([empty], []) == (0, 0, [1.0])


def test_text_is_kept_word_by_word_and_sentences_in_reading_order() -> None:
    units = ["Mix 4 litres of", "water.", "Store dry. Use within 6 months."]

    assert parsing.words_kept("Mix 4 litres of water. water.", units) == (5, 6)
    sentences = ["Mix 4 litres of water.", "Store dry.", "Use within 12 months."]
    assert parsing.sentences_whole(sentences, units) == (2, 3)
    interleaved = ["Mix 4 litres Store dry.", "of water. Use within"]
    assert parsing.sentences_whole(sentences[:1], interleaved) == (0, 1)
    assert parsing.table_numbers([TABLE], ["Fire A1", "A 2"]) == (2, 2)
    # Docling writes typographic characters plainly; both sides are folded alike.
    typographic = ["Fit in a ‘brick bond’ – done."]
    plain = ["Fit in a 'brick bond' - done."]
    assert parsing.sentences_whole(typographic, plain) == (1, 1)


def test_a_pair_is_kept_on_one_line_or_the_next() -> None:
    units = ["Reaction to fire: Class A1", "pH", "11.2", "Colour"]
    pairs = [["Reaction to fire:", "Class A1"], ["pH", "11.2"], ["Colour", "White"]]

    assert parsing.pairs_kept(pairs, units) == (2, 3)


def page_scores(found: int) -> dict[str, object]:
    measures = {measure: (found, 2) for measure in parsing.GATE}
    return {**measures, "table_shares": [found / 2], "grid": (0, 0), "grid_shares": []}


def test_the_gate_needs_every_measure_and_no_weak_table() -> None:
    perfect = page_scores(2)

    passed = parsing.summarise(
        {"pypdf": [page_scores(1)], "docling": [perfect]}, [9.0, 1.0]
    )
    failed = parsing.summarise({"pypdf": [perfect], "docling": [page_scores(1)]}, [1.0])

    assert all(passed["gate"].values())
    assert passed["seconds"] == {"mean": 5.0, "median": 5.0, "first": 9.0}
    assert not any(failed["gate"].values())
    assert (
        parsing.pooled([{m: (0, 0) for m in [*parsing.GATE, "grid"]}])["cells"] == 1.0
    )
    text = parsing.markdown(failed)
    assert "| cells | 1.000 | 0.500 | >= 0.95 |" in text
    assert "Lowest table (docling): 0.500 (>= 0.8)" in text
    assert "- 2. text kept: FAIL" in text


def test_the_command_line_runs_both_parsers_and_saves_their_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "pages"
    folder.mkdir()
    truth = {"pages": [{
        "number": 1, "entry": "file:" + "a" * 64, "page": 2,
        "tables": [TABLE], "pairs": [["Grade", "M5"]],
        "sentences": ["Mix 4 litres of water."],
    }]}  # fmt: skip
    (folder / "truth.json").write_text(json.dumps(truth))
    sets.register("pages", "invented", tmp_path, tmp_path / "sets.json")
    text = "Mix 4 litres of water.\nGrade M5\nFire A1 A2"
    monkeypatch.setattr(cli, "text_layer", lambda path, page: text)
    elements = [
        Element(page=2, kind="paragraph", text="Mix 4 litres of water."),
        Element(page=2, kind="paragraph", text="Grade M5"),
        Element(page=2, kind="table_row", text="Fire — Class i: A1; Class ii: A2",
                cells=(("Property", "Fire"), ("Class i", "A1"), ("Class ii", "A2"))),
        Element(page=2, kind="figure", text=""),
        Element(page=3, kind="paragraph", text="the next page"),
    ]  # fmt: skip
    asked = []

    def read_pdf(path: Path, first: int, last: int, vlm: str, stats: Any) -> Any:
        asked.append(vlm)
        if vlm:
            stats["tables"] += 1
        return elements

    monkeypatch.setattr(pdf, "read_pdf", read_pdf)
    out = tmp_path / "out"
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]

    assert cli.main([*base, "parsing", "pages", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "| cells | 0.000 | 1.000 | >= 0.95 |" in printed
    saved = json.loads((out / "parsed.json").read_text(encoding="utf-8"))
    assert saved["1"]["pypdf"] == text.splitlines()
    assert len(saved["1"]["docling"]) == 4  # page 3 left out
    assert cli.main([*base, "parsing", "pages", "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["docling"]["cells"] == 1.0
    assert cli.text_layer.__name__ == "<lambda>"
    vlm = ["--arm", "glm-ocr", "--vlm", "http://vlm"]
    assert cli.main([*base, "parsing", "pages", "--out", str(out), *vlm]) == 0
    assert "| Measure | pypdf | glm-ocr | Gate |" in capsys.readouterr().out
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["tables"] == {"tables": 1}
    assert asked == ["", "", "http://vlm"]


def test_the_text_layer_is_read_page_by_page(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def extract_text(self) -> str | None:
            return self.text

    class Reader:
        def __init__(self, path: Path) -> None:
            self.pages = [Page("first"), Page(None)]

    monkeypatch.setattr(cli, "PdfReader", Reader)

    assert cli.text_layer(Path("a.pdf"), 1) == "first"
    assert cli.text_layer(Path("a.pdf"), 2) == ""


def test_a_transcription_is_scored_by_its_words() -> None:
    truth = "lime | green T: 01952 728611 Much Wenlock ©"
    answer = "<p>lime green</p> T: 01952 728611 Much Wenlock Shropshire"

    assert parsing.transcription(truth, answer) == {
        "recall": (7, 7),
        "precision": (7, 8),
    }


def test_the_command_line_renders_one_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = []

    class Image:
        width, height = 1190, 1684

        def save(self, path: Path) -> None:
            saved.append(path)

    monkeypatch.setattr(pdf, "page_image", lambda path, page, scale: Image())
    out = tmp_path / "images" / "01-p1.png"

    assert cli.main(["render-page", "a.pdf", "1", str(out), "--scale", "2"]) == 0
    assert saved == [out]
    assert "1190 x 1684" in capsys.readouterr().out


def test_the_command_line_scores_a_model_s_transcriptions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "pages"
    folder.mkdir()
    truth = {"pages": [], "blank": [
        {"number": "b1", "entry": "file:" + "a" * 64, "page": 3,
         "words": "Product Data T: 01952 728611"},
    ]}  # fmt: skip
    (folder / "truth.json").write_text(json.dumps(truth))
    sets.register("pages", "invented", tmp_path, tmp_path / "sets.json")
    answers = ["Product Data T: 01952 728611", "Product Data invented words here"]
    asked = []

    def recognise(image: Any, url: str, prompt: str) -> str:
        asked.append((image, url, prompt))
        return answers.pop(0)

    monkeypatch.setattr(pdf, "page_image", lambda path, page, scale: f"page {page}")
    monkeypatch.setattr(tables, "recognise", recognise)
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]
    command = ["transcription", "pages", "--vlm", "http://vlm", "--prompt", "OCR:"]

    assert cli.main([*base, *command, "--out", str(tmp_path / "out")]) == 0
    assert "recall: 1.000 (bar 0.9)" in capsys.readouterr().out
    assert asked == [("page 3", "http://vlm", "OCR:")]
    saved = json.loads((tmp_path / "out" / "transcription.json").read_text())
    assert saved["pages"]["b1"]["answer"] == "Product Data T: 01952 728611"
    assert cli.main([*base, *command, "--out", str(tmp_path / "out")]) == 1
    assert "FAIL" in capsys.readouterr().out


GRID: dict[str, Any] = {
    "grid": [
        ["Mix", "Class", "Class"],
        ["Mix", "i", "ii"],
        ["Cement", "1", "1"],
        ["Water", "2 ₂", ""],
    ],
    "header_rows": 2,
}


def test_a_value_is_placed_by_its_row_label_and_a_header_above_it() -> None:
    # Docling-like grid: the header rows are not flagged, only laid out above.
    parsed = (("Mix", "Class", "Class"), ("", "i", "ii"), ("Cement", "1", "1"),
              ("Water", "2 2", ""))  # fmt: skip
    swapped = (("", "ii", "i"), ("Cement", "1", "0"), ("Water", "22", ""))

    assert parsing.grid_cells([GRID], [parsed]) == (3, 3, [1.0])
    assert parsing.grid_cells([GRID], [swapped])[:2] == (1, 3)
    no_header: dict[str, Any] = {"grid": [["Colour", "White"]], "header_rows": 0}
    assert parsing.grid_cells([no_header, TABLE], [(("Colour", "White"),)]) == (
        1, 1, [1.0],
    )  # fmt: skip
    assert parsing.grid_fold("CO₂e") == "co2e"
    assert parsing.header_and_rows(GRID) == (["Mix", "i", "ii"], GRID["grid"][2:])
    assert parsing.header_and_rows(no_header)[0] == ["", ""]


def test_round_3_is_gated_on_values_in_their_row_and_column() -> None:
    page = {"tables": [GRID], "pairs": [], "sentences": []}
    parsed = (("Mix", "i", "ii"), ("Cement", "1", "1"), ("Water", "22", ""))
    good = parsing.score_page(page, ["Cement 1 1 Water 22"], [], "Cement 1", [parsed])
    bad = parsing.score_page(page, ["Cement"], [], "Cement 1", [])

    passed = parsing.summarise({"pypdf": [bad], "docling": [good]}, [1.0])
    failed = parsing.summarise({"pypdf": [good], "docling": [bad]}, [1.0])

    assert passed["grid_mode"] and all(passed["gate"].values())
    assert list(failed["gate"]) == [
        "1. table values in their row and column",
        "2. text kept",
        "3. table numbers",
    ]
    assert not failed["gate"]["1. table values in their row and column"]
    text = parsing.markdown(failed)
    assert "| grid | 1.000 | 0.000 | >= 0.95 |" in text
    assert "| pairs | 1.000 | 1.000 | reported |" in text

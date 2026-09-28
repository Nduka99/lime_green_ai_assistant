"""Scoring PDF parsers against ground truth (X8). Every page and text is invented."""

import json
from pathlib import Path

import pytest

from evaluation import __main__ as cli
from evaluation import parsing, sets
from limespec import pdf
from limespec.elements import Element

TABLE = {"header": ["Property", "Class i", "Class ii"], "rows": [["Fire", "A1", "A2"]]}


def test_a_cell_is_found_by_its_row_label_column_header_and_value() -> None:
    rows: parsing.Rows = [
        (),
        (("Property", "Fire"), ("Performance Class i", "A1"),
         ("Performance Class ii", "A 2")),
    ]  # fmt: skip
    wrong: parsing.Rows = [
        (("Property", "Fire"), ("Class ii", "A1"), ("Class i", "A2"))
    ]

    assert parsing.table_cells([TABLE], rows) == (2, 2, [1.0])
    assert parsing.table_cells([TABLE], wrong) == (0, 2, [0.0])
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


def test_a_pair_is_kept_on_one_line_or_the_next() -> None:
    units = ["Reaction to fire: Class A1", "pH", "11.2", "Colour"]
    pairs = [["Reaction to fire:", "Class A1"], ["pH", "11.2"], ["Colour", "White"]]

    assert parsing.pairs_kept(pairs, units) == (2, 3)


def page_scores(found: int) -> dict[str, object]:
    measures = {measure: (found, 2) for measure in parsing.GATE}
    return {**measures, "table_shares": [found / 2]}


def test_the_gate_needs_every_measure_and_no_weak_table() -> None:
    perfect = page_scores(2)

    passed = parsing.summarise(
        {"pypdf": [page_scores(1)], "docling": [perfect]}, [9.0, 1.0]
    )
    failed = parsing.summarise({"pypdf": [perfect], "docling": [page_scores(1)]}, [1.0])

    assert all(passed["gate"].values())
    assert passed["seconds"] == {"median": 5.0, "first": 9.0}
    assert not any(failed["gate"].values())
    assert parsing.pooled([{m: (0, 0) for m in parsing.GATE}])["cells"] == 1.0
    text = parsing.markdown(failed)
    assert "| cells | 1.000 | 0.500 | ≥ 0.95 |" in text
    assert "Lowest table (docling): 0.500 (≥ 0.8)" in text
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
    monkeypatch.setattr(pdf, "read_pdf", lambda path, first, last: elements)
    out = tmp_path / "out"
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]

    assert cli.main([*base, "parsing", "pages", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "| cells | 0.000 | 1.000 | ≥ 0.95 |" in printed
    saved = json.loads((out / "parsed.json").read_text(encoding="utf-8"))
    assert saved["1"]["pypdf"] == text.splitlines()
    assert len(saved["1"]["docling"]) == 4  # page 3 left out
    assert cli.main([*base, "parsing", "pages", "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["docling"]["cells"] == 1.0
    assert cli.text_layer.__name__ == "<lambda>"


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

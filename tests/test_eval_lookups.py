"""X9's table lookups and quote retrieval. Every page, table and passage is invented."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import lookups, metrics, sets
from limespec import assistant, config, ingest, store
from limespec.models import Passage

URL = "https://example.test/Documents/duro%20dop.pdf"
PAGES = [
    {"number": 1, "entry": "file:aaa", "url": URL, "page": 2, "tables": [
        {"header": ["Property", "Class i", "Class ii"],
         "rows": [["Fire", "A1", "-"], ["Strength", "M5", "M10"], ["", "x", "y"],
                  ["Fire", "A1", "A2"]]},
    ]},
    {"number": 2, "entry": "file:bbb", "url": "https://example.test/sds.pdf", "page": 1,
     "tables": [{"grid": [["", "Section"], ["Name", "Value"], ["CAS", "1305-62-0"]],
                 "header_rows": 2}]},
]  # fmt: skip


def test_each_usable_cell_becomes_one_question() -> None:
    found = lookups.table_questions("demo", PAGES, {URL: "Duro Render — UK DoP"})

    assert [item["question"] for item in found] == [
        "In the Duro Render — UK DoP, what is the Class i for Fire?",
        "In the Duro Render — UK DoP, what is the Class i for Strength?",
        "In the Duro Render — UK DoP, what is the Class ii for Strength?",
        "In the Duro Render — UK DoP, what is the Class ii for Fire?",
        "In the sds, what is the Value for CAS?",  # no site title: the file name
    ]
    assert found[0] == {"id": "demo/1/1/0/1", "set": "x9-tables",
                        "question": found[0]["question"], "sha256": "aaa", "page": 2,
                        "evidence": ["Fire", "A1"], "cluster": "demo/1/1"}  # fmt: skip


KEY = {"conversations": [{"id": "c01", "turns": [
    {"id": "c01t1", "standalone_question": "Is Duro fire rated?", "parts": [
        {"id": "p1", "evidence": [{"source": "c01-s1", "quote": "Fire A1"},
                                  {"source": "c01-s2", "quote": "A page quote"},
                                  {"source": "c01-s3", "quote": "An image's alt"}]}]},
    {"id": "c01t2", "standalone_question": "Thanks", "parts": []},
]}]}  # fmt: skip
PLAN = {"plan": [{"id": "c01", "sources": ["file:aaa", "page:products", "file:img"]}]}


def test_every_conv_v1_quote_from_a_read_pdf_is_an_item() -> None:
    assert lookups.quote_items(KEY, PLAN, {"aaa"}) == [
        {"id": "c01t1/p1/1", "set": "conv-v1", "question": "Is Duro fire rated?",
         "sha256": "aaa", "page": None, "evidence": ["Fire A1"], "cluster": "c01t1"},
    ]  # fmt: skip


def passage(number: int, text: str, page: int | None = 2, url: str = URL) -> Passage:
    return Passage(number, url, "Duro Render — UK DoP", "", text, "2026-09-12", page)


def test_a_passage_is_relevant_where_a_claim_could_quote_the_evidence() -> None:
    item = lookups.table_questions("demo", PAGES, {})[0]
    quote = lookups.quote_items(KEY, PLAN, {"aaa"})[0]
    row = passage(1, "Property | Class i\nFire | A1 | -")

    assert lookups.relevant(row, item, URL)
    assert not lookups.relevant(row, item, "https://example.test/other.pdf")
    assert not lookups.relevant(passage(1, row.text, page=3), item, URL)
    assert not lookups.relevant(passage(1, "Fire is A2"), item, URL)
    assert lookups.relevant(passage(1, row.text, page=9), quote, URL)  # any page


def test_an_item_is_scored_by_its_first_relevant_rank_and_its_ceiling() -> None:
    item = lookups.table_questions("demo", PAGES, {})[0]
    miss = passage(1, "Strength | M5")
    hit = passage(2, "Fire | A1")

    found = lookups.score_item(item, [miss, hit], [miss, hit], URL)
    lost = lookups.score_item(item, [miss] * 9 + [hit], [miss], URL)

    assert found == {"id": item["id"], "set": "x9-tables", "cluster": "demo/1/1",
                     "success": 1.0, "reciprocal": 0.5, "ceiling": 1.0}  # fmt: skip
    assert (lost["success"], lost["reciprocal"], lost["ceiling"]) == (0.0, 0.0, 0.0)


def result(item: str, name: str, success: float, cluster: str = "t1") -> dict[str, Any]:
    return {"id": item, "set": name, "cluster": cluster, "success": success,
            "reciprocal": success / 2, "ceiling": 1.0}  # fmt: skip


def test_sets_are_summarised_and_arms_compared_by_resampled_clusters() -> None:
    baseline = [result("a", "x9-tables", 0.0), result("b", "x9-tables", 0.0, "t2"),
                result("q", "conv-v1", 1.0)]  # fmt: skip
    arm = [result("a", "x9-tables", 1.0), result("b", "x9-tables", 1.0, "t2"),
           result("q", "conv-v1", 1.0)]  # fmt: skip

    assert lookups.summary(arm)["x9-tables"] == {
        "count": 2,
        "success": 1.0,
        "mrr": 0.5,
        "ceiling": 1.0,
    }
    assert lookups.compare(arm, baseline, "x9-tables") == {
        "difference": 1.0,
        "low": 1.0,
        "high": 1.0,
    }
    mixed = metrics.paired_cluster_bootstrap([1, 0, 1], [0, 0, 0], ["a", "a", "b"])
    assert mixed["low"] <= mixed["difference"] <= mixed["high"]


def arm(lookups_score: float, quotes: float, passages: int) -> dict[str, Any]:
    return {"passages": passages, "summary": {
        "x9-tables": {"success": lookups_score},
        "conv-v1": {"success": quotes, "count": 40},
    }}  # fmt: skip


def test_the_selection_rule_keeps_the_baseline_unless_an_arm_clearly_wins() -> None:
    table = arm(0.60, 0.80, 1000)

    assert lookups.select({"table": table, "rows": arm(0.61, 0.80, 900)}) == "table"
    assert lookups.select({"table": table, "rows": arm(0.70, 0.80, 2000)}) == "rows"
    # 0.775 is one quote in 40 below the baseline: still eligible; two is not.
    assert lookups.select({"table": table, "rows": arm(0.70, 0.775, 2000)}) == "rows"
    assert lookups.select({"table": table, "rows": arm(0.70, 0.75, 2000)}) == "table"
    both = {"table": table, "rows": arm(0.70, 0.8, 2000), "both": arm(0.69, 0.8, 1500)}
    assert lookups.select(both) == "both"  # a tie: fewer passages


def registered(root: Path) -> list[str]:
    """The three X8 truth sets, conv-v1 and x9-tables, sealed in `root`."""
    for name in cli.X8_SETS:
        (root / name).mkdir()
        truth = {"pages": PAGES if name == "x8-pages" else []}
        (root / name / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
        sets.register(name, "invented", root, root / "sets.json")
    (root / "conv-v1").mkdir()
    (root / "conv-v1" / "key.json").write_text(json.dumps(KEY), encoding="utf-8")
    (root / "conv-v1" / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    sets.register("conv-v1", "invented", root, root / "sets.json")
    return ["--root", str(root), "--registry", str(root / "sets.json")]


def test_table_questions_are_written_from_the_sealed_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = registered(tmp_path)
    monkeypatch.setattr(ingest, "site_html", lambda: [])
    out = tmp_path / "x9-tables" / "questions.json"

    assert cli.main([*base, "table-questions", "--out", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["questions"]) == 5
    assert "5 table lookups" in capsys.readouterr().out


def test_an_index_version_is_scored_on_both_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = registered(tmp_path)
    out = tmp_path / "x9-tables" / "questions.json"
    monkeypatch.setattr(ingest, "site_html", lambda: [])
    cli.main([*base, "table-questions", "--out", str(out)])
    sets.register("x9-tables", "invented", tmp_path, tmp_path / "sets.json")
    readings = tmp_path / "elements"
    readings.mkdir()
    for sha256, url in (("aaa", URL), ("bbb", "https://example.test/sds.pdf")):
        reading = {"sha256": sha256, "urls": [url]}
        (readings / f"{sha256}.json").write_text(json.dumps(reading), encoding="utf-8")
    (readings / "report.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "READINGS", readings)

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    rows = [passage(1, "Property | Class i | Class ii\nFire | A1 | A2")]
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "search", lambda conn, version, question, e, r: rows)
    monkeypatch.setattr(store, "document_passages", lambda conn, version, url: rows)
    monkeypatch.setattr(store, "passage_count", lambda conn, version: 7)
    run = tmp_path / "runs" / "table.json"

    assert (
        cli.main([*base, "quote-retrieval", "--version", "4", "--out", str(run)]) == 0
    )
    saved = json.loads(run.read_text(encoding="utf-8"))
    assert (saved["version"], saved["passages"]) == (4, 7)
    assert saved["summary"]["x9-tables"]["success"] == 0.4  # 2 of 5
    assert saved["summary"]["conv-v1"]["success"] == 1.0
    assert "7 passages in version 4" in capsys.readouterr().out

    assert cli.main(["select-form", f"table={run}", f"rows={run}"]) == 0
    assert "selected: table" in capsys.readouterr().out
    assert cli.main(["select-form", f"rows={run}"]) == 1

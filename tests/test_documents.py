"""Reading every stored PDF, each in its own process. Every document, reading and
process here is invented; no PDF library runs."""

import json
import runpy
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from limespec import acquire, cli, documents, llm, pdf
from limespec.elements import Element

WORDS = "Mix four litres of clean water with each bag for ten minutes please"


def test_stored_pdfs_are_grouped_by_their_content() -> None:
    records = [
        {"url": "https://x.test/a.pdf", "kind": "document", "sha256": "a",
         "content_type": "application/pdf"},
        {"url": "https://x.test/copy-of-a.pdf", "kind": "document", "sha256": "a",
         "content_type": "application/pdf"},
        {"url": "https://x.test/b.jpg", "kind": "image", "sha256": "b",
         "content_type": "image/jpeg"},
        {"url": "https://gov.test/c.pdf", "kind": "external", "sha256": "c",
         "content_type": "application/pdf"},
        {"url": "https://x.test/gone.pdf", "kind": "document", "error": "HTTP 404"},
    ]  # fmt: skip

    assert documents.pdf_files(records) == {
        "a": ["https://x.test/a.pdf", "https://x.test/copy-of-a.pdf"]
    }


def test_a_fingerprint_names_the_code_packages_and_vision_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get(url: str, **kwargs: Any) -> httpx.Response:
        assert url == "http://vlm/v1/models"
        body = {"data": [{"id": "GLM-OCR-f16.gguf"}]}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(llm, "auth", lambda: {})

    plain = documents.fingerprint("")
    with_model = documents.fingerprint("http://vlm")

    assert len(plain["reader_sha256"]) == 64
    assert set(plain["packages"]) == set(documents.PACKAGES)
    assert plain["vision_model"] == ""
    assert with_model["vision_model"] == "GLM-OCR-f16.gguf"
    assert with_model["reader_sha256"] == plain["reader_sha256"]


def test_each_page_is_checked_against_its_text_layer() -> None:
    found = [
        Element(1, "paragraph", WORDS),
        Element(2, "paragraph", "Mix four litres"),
        Element(2, "recovered", "of clean water with each bag for ten minutes please"),
        Element(3, "paragraph", "Section A-A"),
        Element(4, "figure", ""),
    ]
    layers = {1: WORDS, 2: WORDS, 3: "Section A-A", 5: ""}
    grades = {1: "excellent", 2: "fair", 4: "poor"}

    checked = documents.validate(found, layers, grades)

    pages = {page["page"]: page for page in checked["pages"]}
    assert (pages[1]["kept"], pages[1]["words"], pages[1]["flags"]) == (13, 13, [])
    assert (pages[2]["kept"], pages[2]["recovered"]) == (3, 1)
    assert pages[2]["flags"] == ["low coverage"]
    assert pages[3]["flags"] == ["little or no text layer"]
    assert pages[4]["flags"] == ["no text layer to check", "poor confidence"]
    assert pages[5]["grade"] == "unspecified"
    assert checked["flagged"] == 4


def test_one_document_is_read_with_its_tables_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read_pdf(
        path: Path, vlm: str, stats: Counter[str], grades: dict[int, str]
    ) -> Any:
        assert (path.name, vlm) == ("abc", "http://vlm")
        stats["tables"] += 2
        grades[1] = "good"
        return [Element(1, "paragraph", WORDS)]

    monkeypatch.setattr(pdf, "read_pdf", read_pdf)
    monkeypatch.setattr(pdf, "text_layers", lambda path: {1: WORDS})

    reading = documents.read_one("abc", "http://vlm")

    assert reading["sha256"] == "abc"
    assert reading["tables"] == {"tables": 2}
    assert reading["validation"]["pages"][0]["grade"] == "good"
    assert reading["elements"][0]["text"] == WORDS
    assert isinstance(reading["seconds"], float)


class Child:
    """Stands in for subprocess.run: each document's outcomes, in order."""

    def __init__(self, outcomes: dict[str, list[str]]) -> None:
        self.outcomes = outcomes
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        self.commands.append(command)
        sha256, part = command[4], Path(command[5])
        outcome = self.outcomes[sha256].pop(0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if outcome == "ok":
            reading = {"sha256": sha256, "seconds": 2.5, "tables": {"tables": 1},
                       "validation": {"pages": [
                           {"page": 1, "words": 20, "kept": 20, "recovered": 0,
                            "grade": "good", "flags": []},
                           {"page": 2, "words": 20, "kept": 10, "recovered": 3,
                            "grade": "fair", "flags": ["low coverage"]}],
                           "flagged": 1},
                       "elements": []}  # fmt: skip
            part.write_text(json.dumps(reading), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        if outcome == "silent":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 127, "", "Windows fatal exception")


def test_a_run_reads_each_document_once_retries_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(documents, "fingerprint", lambda vlm: {"vision_model": vlm})
    done = {"sha256": "old", "seconds": 1.0, "tables": {}, "urls": ["u/old.pdf"],
            "validation": {"pages": [], "flagged": 0},
            "fingerprint": {"vision_model": "http://vlm"}}  # fmt: skip
    (tmp_path / "old.json").write_text(json.dumps(done), encoding="utf-8")
    files = {"old": ["u/old.pdf"], "new": ["u/new.pdf"], "retried": ["u/r.pdf"],
             "broken": ["u/b.pdf"], "stale": ["u/s.pdf"]}  # fmt: skip
    stale = done | {"fingerprint": {"vision_model": ""}}
    (tmp_path / "stale.json").write_text(json.dumps(stale), encoding="utf-8")
    child = Child({"new": ["ok"], "retried": ["crash", "ok"],
                   "broken": ["timeout", "silent"], "stale": ["ok"]})  # fmt: skip

    report = documents.run_all(files, "http://vlm", tmp_path, run=child)

    assert report["skipped"] == ["old"]
    assert report["read"] == ["new", "retried", "stale"]
    assert report["failed"]["broken"]["errors"] == [
        "timed out after 1800 s",
        "exit 0: ",
    ]
    assert child.commands[0][-2:] == ["--vlm", "http://vlm"]
    saved = json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))
    assert saved["urls"] == ["u/new.pdf"]
    assert saved["fingerprint"] == {"vision_model": "http://vlm"}
    assert not (tmp_path / "new.part.json").exists()
    assert "Windows fatal exception" in documents.attempt(
        "x", tmp_path / "x.json", "", Child({"x": ["crash"]})
    )
    totals = report["summary"]["totals"]
    assert totals == {"documents": 4, "seconds": 8.5, "tables": 3, "pages": 6,
                      "recovered lines": 9}  # fmt: skip
    assert [page["url"] for page in report["summary"]["flagged"]] == [
        "u/new.pdf",
        "u/r.pdf",
        "u/s.pdf",
    ]
    assert json.loads((tmp_path / "report.json").read_text())["read"] == report["read"]
    plain = Child({"x": ["ok"]})
    documents.attempt("x", tmp_path / "x.json", "", plain)
    assert "--vlm" not in plain.commands[0]


def test_the_command_line_reads_every_pdf_and_prints_the_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquire, "read_manifest", lambda: [])
    report = {
        "read": ["a"], "skipped": [], "failed": {"b": {"urls": ["u/b.pdf"],
                                                      "errors": ["exit 127: fault"]}},
        "summary": {"totals": {"documents": 1, "seconds": 2.5},
                    "flagged": [{"url": "u/a.pdf", "page": 2, "flags": ["low coverage"],
                                 "kept": 10, "words": 20, "grade": "fair"}]},
    }  # fmt: skip
    monkeypatch.setattr(documents, "run_all", lambda files, vlm, out: report)
    monkeypatch.setattr(llm, "healthy", lambda url: url == "http://up")

    assert cli.main(["read-pdfs", "--vlm", "http://down"]) == 1
    assert "no vision model ready" in capsys.readouterr().err
    assert cli.main(["read-pdfs", "--vlm", "http://up"]) == 1
    printed = capsys.readouterr().out
    assert "0 PDFs: 1 read, 0 already read, 1 failed" in printed
    assert "failed u/b.pdf (b): exit 127: fault" in printed
    assert "seconds: 2.5" in printed and "documents: 1" in printed
    assert "flagged a.pdf p2: low coverage (10/20 words, fair)" in printed
    report["failed"] = {}
    assert cli.main(["read-pdfs"]) == 0

    monkeypatch.setattr(documents, "read_one", lambda sha, vlm: {"sha256": sha})
    out = tmp_path / "one.json"
    assert cli.main(["read-pdf", "abc", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"sha256": "abc"}


def test_the_package_runs_as_a_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["limespec", "--help"])

    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("limespec", run_name="__main__")

    assert stopped.value.code == 0

"""Word documents (X43 A3a). Invented documents; LibreOffice and Docling are faked."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from limespec import config, office
from limespec.elements import Element


def test_a_document_is_laid_out_by_libreoffice_into_a_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = tmp_path / "abc123"
    stored.write_bytes(b"docx bytes")
    asked: list[list[str]] = []

    def run(command: list[str], **options: Any) -> None:
        asked.append(command)
        out = Path(command[command.index("--outdir") + 1])
        (out / "abc123.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(config, "LIBREOFFICE", Path("soffice"))

    pdf = office.render_pdf(stored, tmp_path / "out")

    assert pdf == tmp_path / "out" / "abc123.pdf"
    assert (tmp_path / "out" / "abc123.docx").read_bytes() == b"docx bytes"
    assert asked[0][:4] == ["soffice", asked[0][1], "--headless", "--convert-to"]
    assert asked[0][1].startswith("-env:UserInstallation=file:")

    monkeypatch.setattr(subprocess, "run", lambda command, **options: None)
    with pytest.raises(RuntimeError, match="no PDF"):
        office.render_pdf(tmp_path / "out" / "abc123.docx", tmp_path / "empty")


class Label:
    def __init__(self, value: str) -> None:
        self.value = value


class Item:
    def __init__(self, label: str, text: str = "", bold: bool = False) -> None:
        self.label = Label(label)
        self.text = text
        self.formatting = type("Formatting", (), {"bold": bold})()
        cells = [
            [type("Cell", (), {"text": t})() for t in row] for row in (["A", "1"],)
        ]
        self.data = type("Data", (), {"grid": cells})()

    def caption_text(self, document: object) -> str:
        return "CE mark"


def test_docling_word_items_become_headings_paragraphs_tables_and_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import docling.document_converter

    items = [
        Item("text", "EC Declaration of Performance", bold=True),
        Item("text", "Reaction to fire:", bold=True),
        Item("text", ""),
        Item("text", "Declares that the  product"),
        Item("table"),
        Item("picture"),
    ]
    document = type(
        "Document", (), {"iterate_items": lambda self: [(i, 1) for i in items]}
    )()

    class Converter:
        def __init__(self, allowed_formats: object) -> None:
            pass

        def convert(self, stream: object) -> object:
            return type("Result", (), {"document": document})()

    monkeypatch.setattr(docling.document_converter, "DocumentConverter", Converter)
    path = tmp_path / "d.docx"
    path.write_bytes(b"x")

    found = office.read_docx(path)

    title = ("EC Declaration of Performance",)
    assert found == [
        Element(1, "heading", "EC Declaration of Performance"),
        Element(1, "paragraph", "Reaction to fire:", title),  # a lead-in, not a heading
        Element(1, "paragraph", "Declares that the product", title),
        Element(1, "table", "A | 1", title, table=1, grid=(("A", "1"),)),
        Element(1, "figure", "CE mark", title),
    ]

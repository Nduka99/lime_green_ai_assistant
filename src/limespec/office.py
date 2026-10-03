"""Word documents (X43 A3a): the site's Declarations of Performance.

A Word file has no fixed layout: Word lays it out when it is opened. Two readings are
compared against truth judged from each page as drawn:
- `render_pdf`: LibreOffice lays the document out and writes a PDF, which the measured
  PDF reading (`pdf.read_pdf`) then reads, figures and tables included;
- `read_docx`: Docling's Word reader, from the file's own structure.

Used when building an index, never by the API (the `ingest` group, and LibreOffice
unpacked into tools/, which is not committed).
"""

import shutil
import subprocess
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Any

from limespec import config
from limespec.elements import Element, grid_text

TIMEOUT_SECONDS = 300  # LibreOffice starts in seconds; a declaration converts in one
HEADING_LENGTH = 100  # characters: a bold paragraph no longer is a heading


def render_pdf(docx: Path, out: Path) -> Path:
    """The document as LibreOffice lays it out, written as a PDF in `out`. LibreOffice
    runs headless with a profile of its own, so no user setting changes the layout."""
    out.mkdir(parents=True, exist_ok=True)
    source = out / f"{docx.stem}.docx"
    if source != docx:
        shutil.copyfile(docx, source)
    profile = (out / "libreoffice-profile").resolve().as_uri()
    command = [
        str(config.LIBREOFFICE),
        f"-env:UserInstallation={profile}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out),
        str(source),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    pdf = out / f"{docx.stem}.pdf"
    if not pdf.exists():
        raise RuntimeError(f"LibreOffice wrote no PDF for {docx}")
    return pdf


def read_docx(path: Path) -> list[Element]:
    """Docling's reading of a Word file as elements, all on page 1 (the file has no
    pages). A short paragraph set in bold is a heading; a table is its grid; a picture
    is a figure."""
    from docling.datamodel.base_models import DocumentStream, InputFormat
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter(allowed_formats=[InputFormat.DOCX])
    stream = DocumentStream(name="document.docx", stream=BytesIO(path.read_bytes()))
    document = converter.convert(stream).document
    found: list[Element] = []
    section: tuple[str, ...] = ()
    tables = 0
    # Items differ by kind (text, table, picture), so they are read field by field.
    items: Iterable[tuple[Any, int]] = document.iterate_items()
    for item, _ in items:
        label = item.label.value
        if label == "table":
            tables += 1
            grid = tuple(tuple(cell.text for cell in row) for row in item.data.grid)
            found.append(
                Element(1, "table", grid_text(grid), section, table=tables, grid=grid)
            )
            continue
        if label == "picture":
            found.append(Element(1, "figure", item.caption_text(document), section))
            continue
        text = " ".join(str(getattr(item, "text", "")).split())
        if not text:
            continue
        bold = bool(getattr(getattr(item, "formatting", None), "bold", False))
        if bold and len(text) <= HEADING_LENGTH and not text.endswith(":"):
            found.append(Element(1, "heading", text, section))
            section = (text,)
        else:
            found.append(Element(1, "paragraph", text, section))
    return found

"""Lime Green's PDFs read into elements for the index (PLAN Phase 3, S2; ADR 0027).

Each distinct file (by SHA-256) is read in its own child process, so a native fault
in the PDF libraries, or a document that never finishes, stops only that document;
it is tried once more, then reported as failed. Each reading is saved with a
fingerprint of everything that produced it (reader code, package versions, the
vision model), so a run skips documents already read the same way and resumes
after an interruption. Each reading carries a validation record per page: how much
of the words a reader sees (by pdfium) the parser's own text holds, the lines
recovered, the words not shown, and Docling's confidence grade; pages below the bar
are flagged in the run's report.
"""

import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from limespec import acquire, config, ingest, layout, llm, office, pdf, store
from limespec.passages import pdf_passages

OUT = config.READINGS
ATTEMPTS = 2
TIMEOUT_SECONDS = 1800.0  # the longest guide with a vision model takes minutes
LOW_COVERAGE = 0.95  # D84: a page whose own text holds less of its layer is flagged
MIN_WORDS = 10  # a page with fewer text-layer words has no text to check
PACKAGES = ("docling-slim", "docling-core", "docling-parse", "docling-ibm-models",
            "pypdfium2", "torch", "pylatexenc", "pypdf")  # fmt: skip
READER = (
    "elements.py",
    "pdf.py",
    "recovery.py",
    "rendering.py",
    "tables.py",
    "visibility.py",
)
# A Word file is laid out by LibreOffice, then read as a PDF (X43 A3a): its readings
# also depend on that code, kept out of the PDFs' fingerprint so they are not redone.
WORD_READER = ("office.py",)
WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
READABLE = ("application/pdf", WORD)
EXTERNAL_PUBLISHER = "GOV.UK"  # the only external documents collected (OGL, D73)

Run = Any  # subprocess.run, or a stand-in in tests


def pdf_files(records: list[acquire.Record]) -> dict[str, list[str]]:
    """Each stored document by SHA-256, with every URL it was fetched from: the site's
    PDFs and Word files, and the openly licensed external PDFs (X43)."""
    files: dict[str, list[str]] = {}
    for record in records:
        if record.get("kind") in ("document", "external") and "sha256" in record:
            if record.get("content_type") in READABLE:
                files.setdefault(str(record["sha256"]), []).append(str(record["url"]))
    return files


def is_word(path: Path) -> bool:
    """Whether a stored file is a Word document (a zip package), not a PDF."""
    with path.open("rb") as file:
        return file.read(4) == b"PK"


def fingerprint(vlm: str, word: bool = False) -> dict[str, Any]:
    """What a reading depends on: the reader's own code (and for a Word file the code
    that lays it out), the packages it uses and, when tables are read again, the
    model the vision server has loaded."""
    code = hashlib.sha256()
    for name in READER + (WORD_READER if word else ()):
        code.update((Path(pdf.__file__).parent / name).read_bytes())
    found: dict[str, Any] = {
        "reader_sha256": code.hexdigest(),
        "packages": {name: version(name) for name in PACKAGES},
        "vision_model": "",
    }
    if vlm:
        response = httpx.get(f"{vlm}/v1/models", headers=llm.auth(), timeout=30.0)
        response.raise_for_status()
        found["vision_model"] = response.json()["data"][0]["id"]
    return found


def validate(
    checks: dict[int, dict[str, int]], grades: dict[int, str]
) -> dict[str, Any]:
    """Per page: the words pdfium reads where the page shows them, how many the
    parser's own reading holds, words not shown (left out of the index), lines
    recovered, Docling's lowest confidence grade, and flags."""
    pages = []
    for number, check in sorted(checks.items()):
        flags = []
        if check["words"] < MIN_WORDS:
            flags.append("little or no text")
        elif check["kept"] / check["words"] < LOW_COVERAGE:
            flags.append("low coverage")
        if grades.get(number) == "poor":
            flags.append("poor confidence")
        grade = grades.get(number, "unspecified")
        pages.append({"page": number, **check, "grade": grade, "flags": flags})
    return {"pages": pages, "flagged": sum(bool(page["flags"]) for page in pages)}


def read_one(sha256: str, vlm: str) -> dict[str, Any]:
    """One document read into elements, with its validation (run in a child)."""
    path = acquire.store_path(sha256)
    if is_word(path):
        path = office.render_pdf(path, OUT / "rendered")
    stats: Counter[str] = Counter()
    grades: dict[int, str] = {}
    checks: dict[int, dict[str, int]] = {}
    started = time.perf_counter()
    found = pdf.read_pdf(path, vlm=vlm, stats=stats, grades=grades, checks=checks)
    seconds = round(time.perf_counter() - started, 1)
    return {
        "sha256": sha256,
        "seconds": seconds,
        "tables": dict(stats),
        "validation": validate(checks, grades),
        "elements": [asdict(element) for element in found],
    }


def current(target: Path, found: dict[str, Any]) -> bool:
    """Whether a saved reading was made exactly as a new one would be."""
    if not target.exists():
        return False
    saved = json.loads(target.read_text(encoding="utf-8"))
    return bool(saved.get("fingerprint") == found)


def attempt(sha256: str, part: Path, vlm: str, run: Run) -> str:
    """Read one document in a child process; the error, or "" when it worked."""
    command = [sys.executable, "-m", "limespec", "read-pdf", sha256, str(part)]
    if vlm:
        command += ["--vlm", vlm]
    try:
        done = run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT_SECONDS:.0f} s"
    if done.returncode != 0 or not part.exists():
        tail = (done.stderr or "").strip().splitlines()[-1:] or [""]
        return f"exit {done.returncode}: {tail[0][:300]}"
    return ""


def run_all(
    files: dict[str, list[str]], vlm: str, out: Path, run: Run = subprocess.run
) -> dict[str, Any]:
    """Read every file not already read the same way; the run's report."""
    prints = {False: fingerprint(vlm), True: fingerprint(vlm, word=True)}
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"fingerprint": prints[False], "read": [],
                              "skipped": [], "failed": {}}  # fmt: skip
    for sha256, urls in files.items():
        found = prints[is_word(acquire.store_path(sha256))]
        target = out / f"{sha256}.json"
        if current(target, found):
            report["skipped"].append(sha256)
            continue
        part = out / f"{sha256}.part.json"
        errors = []
        for _ in range(ATTEMPTS):
            error = attempt(sha256, part, vlm, run)
            if not error:
                break
            errors.append(error)
        if len(errors) == ATTEMPTS:
            report["failed"][sha256] = {"urls": urls, "errors": errors}
            continue
        reading = json.loads(part.read_text(encoding="utf-8"))
        reading |= {"urls": urls, "fingerprint": found}
        text = json.dumps(reading, indent=1, ensure_ascii=False) + "\n"
        part.write_text(text, encoding="utf-8", newline="\n")
        part.replace(target)  # written whole, then moved into place
        report["read"].append(sha256)
    report["summary"] = summary(files, out)
    text = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    (out / "report.json").write_text(text, encoding="utf-8", newline="\n")
    return report


def summary(files: dict[str, list[str]], out: Path) -> dict[str, Any]:
    """Totals over every saved reading, and each flagged page with its document."""
    totals: Counter[str] = Counter()
    flagged = []
    for sha256, urls in files.items():
        target = out / f"{sha256}.json"
        if not target.exists():
            continue
        reading = json.loads(target.read_text(encoding="utf-8"))
        totals["documents"] += 1
        totals["seconds"] += reading["seconds"]
        totals.update(reading["tables"])
        for page in reading["validation"]["pages"]:
            totals["pages"] += 1
            totals["recovered lines"] += page["recovered"]
            totals["words not shown"] += page["hidden"]
            totals["hidden words removed"] += page["removed"]
            if page["flags"]:
                flagged.append({
                    "url": urls[0],
                    "page": page["page"],
                    "flags": page["flags"],
                    "kept": page["kept"],
                    "words": page["words"],
                    "grade": page["grade"],
                })  # fmt: skip
    return {"totals": dict(totals), "flagged": flagged}


def page_breaks(sha256: str) -> dict[int, list[tuple[str, str]]]:
    """Each page's number ranges broken after their hyphen in the document's own text
    layer (`layout.number_breaks`): a Word file's as laid out, a PDF's as stored."""
    import pypdfium2

    path = acquire.store_path(sha256)
    if not path.exists():
        return {}
    if is_word(path):
        path = OUT / "rendered" / f"{sha256}.pdf"
    document = pypdfium2.PdfDocument(str(path))
    try:
        found = {}
        for number in range(len(document)):
            text = document[number].get_textpage().get_text_range()
            breaks = layout.number_breaks(text)
            if breaks:
                found[number + 1] = breaks
        return found
    finally:
        document.close()


def index_documents(
    form: str, titles: dict[str, str], folder: Path = OUT
) -> list[tuple[store.PageRow, list[store.PassageRow]]]:
    """Every saved reading as an index document with its passages, its tables in
    the given X9 form: one document per distinct file, under its first URL, titled
    by the site (`ingest.pdf_titles`) or else by its file name. An external document
    is indexed only while `config.EXTERNAL_SOURCES` lists it (X44 F5)."""
    listed = acquire.read_external(config.EXTERNAL_SOURCES)
    fetched: dict[str, str] = {}
    external: set[str] = set()
    for record in acquire.read_manifest():
        fetched.setdefault(str(record["sha256"]), str(record["fetched_at"]))
        if record.get("kind") == "external":
            external.add(str(record["sha256"]))
    found = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "report.json":
            continue
        reading = json.loads(path.read_text(encoding="utf-8"))
        urls = reading["urls"]
        named = [titles[url] for url in urls if url in titles]
        title = named[0] if named else ingest.file_title(urls[0])
        sha256 = str(reading["sha256"])
        if sha256 in external:
            if not any(url in listed for url in urls):
                continue  # collected once, no longer listed
            title = (
                f"{EXTERNAL_PUBLISHER} — {title}"  # general guidance, not Lime Green's
            )
        page_row: store.PageRow = (urls[0], title, fetched[sha256], sha256)
        breaks = page_breaks(sha256)
        mended = [
            e | {"text": layout.kept_hyphens(e["text"], breaks.get(e.get("page"), []))}
            for e in reading["elements"]
        ]
        # A label and its value on one line are read together (X43 A3a).
        lines = layout.side_by_side([layout.from_record(e) for e in mended])
        elements = [asdict(element) for element in lines]
        rows: list[store.PassageRow] = []
        for heading, context, text, page in pdf_passages(elements, form):
            rows.append((urls[0], title, heading, text, context, page))
        found.append((page_row, rows))
    return found

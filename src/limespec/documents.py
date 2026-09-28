"""Lime Green's PDFs read into elements for the index (PLAN Phase 3, S2; ADR 0027).

Each distinct file (by SHA-256) is read in its own child process, so a native fault
in the PDF libraries, or a document that never finishes, stops only that document;
it is tried once more, then reported as failed. Each reading is saved with a
fingerprint of everything that produced it (reader code, package versions, the
vision model), so a run skips documents already read the same way and resumes
after an interruption. Each reading carries a validation record per page: how much
of the text layer the parser's own text holds, the lines added back, and Docling's
confidence grade; pages below the bar are flagged in the run's report.
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

from limespec import acquire, llm, pdf
from limespec.elements import Element

OUT = Path("data/elements")
ATTEMPTS = 2
TIMEOUT_SECONDS = 1800.0  # the longest guide with a vision model takes minutes
LOW_COVERAGE = 0.95  # D84: a page whose own text holds less of its layer is flagged
MIN_WORDS = 10  # a page with fewer text-layer words has no text to check
PACKAGES = ("docling-slim", "docling-core", "docling-parse", "docling-ibm-models",
            "pypdfium2", "torch", "pylatexenc", "pypdf")  # fmt: skip
READER = ("elements.py", "pdf.py", "rendering.py", "tables.py")

Run = Any  # subprocess.run, or a stand-in in tests


def pdf_files(records: list[acquire.Record]) -> dict[str, list[str]]:
    """Each stored Lime Green PDF by SHA-256, with every URL it was fetched from."""
    files: dict[str, list[str]] = {}
    for record in records:
        if record.get("kind") == "document" and "sha256" in record:
            if record.get("content_type") == "application/pdf":
                files.setdefault(str(record["sha256"]), []).append(str(record["url"]))
    return files


def fingerprint(vlm: str) -> dict[str, Any]:
    """What a reading depends on: the reader's own code, the packages it uses and,
    when tables are read again, the model the vision server has loaded."""
    code = hashlib.sha256()
    for name in READER:
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
    found: list[Element], layers: dict[int, str], grades: dict[int, str]
) -> dict[str, Any]:
    """Per page: text-layer words the parser's own text holds (lines added back left
    out), lines added back, Docling's lowest confidence grade, and flags."""
    pages = []
    for number in sorted(set(layers) | {element.page for element in found}):
        own = [e.text for e in found if e.page == number and e.kind != "recovered"]
        kept, words = pdf.coverage(layers.get(number, ""), " ".join(own))
        flags = []
        if number not in layers:
            flags.append("no text layer to check")
        elif words < MIN_WORDS:
            flags.append("little or no text layer")
        elif kept / words < LOW_COVERAGE:
            flags.append("low coverage")
        if grades.get(number) == "poor":
            flags.append("poor confidence")
        pages.append({
            "page": number,
            "words": words,
            "kept": kept,
            "recovered": sum(e.page == number and e.kind == "recovered" for e in found),
            "grade": grades.get(number, "unspecified"),
            "flags": flags,
        })  # fmt: skip
    return {"pages": pages, "flagged": sum(bool(page["flags"]) for page in pages)}


def read_one(sha256: str, vlm: str) -> dict[str, Any]:
    """One document read into elements, with its validation (run in a child)."""
    path = acquire.store_path(sha256)
    stats: Counter[str] = Counter()
    grades: dict[int, str] = {}
    started = time.perf_counter()
    found = pdf.read_pdf(path, vlm=vlm, stats=stats, grades=grades)
    seconds = round(time.perf_counter() - started, 1)
    return {
        "sha256": sha256,
        "seconds": seconds,
        "tables": dict(stats),
        "validation": validate(found, pdf.text_layers(path), grades),
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
    found = fingerprint(vlm)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"fingerprint": found, "read": [], "skipped": [],
                              "failed": {}}  # fmt: skip
    for sha256, urls in files.items():
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

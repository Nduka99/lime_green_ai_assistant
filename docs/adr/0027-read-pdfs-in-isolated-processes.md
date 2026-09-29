# 0027. Read each PDF in its own process, with a fingerprint and a validation record

- Status: Accepted
- Date: 2026-09-28
- Origin: PLAN Phase 3 (S2, the layout-aware index); experiment X8 and its follow-ups

## Context

X8 chose how Lime Green's PDFs are read: Docling for layout, reading order and text, and
GLM-OCR for each table's structure, spelt in the PDF's own words. It also found that:

- docling-parse, the PDF library under Docling, has native faults on Windows. Its page
  renderer corrupted memory in 1 of 20 documents, silently, and crashed on one guide
  (docling-parse #357). Page images now come from pdfium, which removes both in a run of
  all 97 readable documents, but native code can fail in ways this one run did not show.
- Two figure-exported reports lose text to Type 3 fonts. They are caught only because each
  page is compared with pypdf's text layer.
- GLM-OCR needs the GPU the answer generator uses, so ingestion runs with the generator
  stopped. It is a batch job, not part of serving.

The index must be rebuildable, and anyone must be able to say how each document was read.

## Decision

- **One child process per document**, keyed by the file's SHA-256 (the same file under
  several URLs is read once). A native fault or a document that runs past 30 minutes stops
  only that child. The document is tried once more, then reported as failed, never skipped
  silently. Memory is returned to the system after every document.
- **Readings are saved, not just used.** Each document's elements go to
  `data/elements/<sha256>.json` (git-ignored), written whole and then moved into place. The
  file records a fingerprint of everything that produced it:
  - the SHA-256 of the reader's code (`elements.py`, `pdf.py`, `rendering.py`, `tables.py`);
  - the versions of Docling, docling-parse, pdfium, PyTorch and the other reading packages;
  - the model the vision server reports.

  A run skips a document already read with the same fingerprint, so an interrupted run
  resumes, and a change to any input re-reads everything it affects.
- **Every page is validated** against the PDF's text layer, and each page records:
  - how many of the layer's words the parser's own text holds;
  - how many lines were added back from the layer;
  - Docling's lowest confidence grade.

  Pages are flagged for coverage below 0.95 (decision D84), little or no text layer, no text
  layer to check (an encrypted file), or a poor grade. The run writes
  `data/elements/report.json` with totals, failures and every flagged page.
- **No silent change of configuration.** With `--vlm`, the run refuses to start unless the
  vision server answers its health check, so a run never quietly falls back to Docling's own
  tables. Starting that server and stopping the generator are done beforehand, outside the
  runner.

Commands: `uv run --group ingest python -m limespec read-pdfs [--vlm URL]`. Each child runs
`limespec read-pdf SHA OUT`.

## Alternatives considered

- **One process for everything:** fastest, but one fault ends the run, and #357 showed that
  faults can corrupt data without ending the process.
- **A pool of long-lived workers** (`ProcessPoolExecutor`, `max_tasks_per_child`): reuses
  loaded models, but a crashed worker breaks the pool, which then has to be rebuilt, and a
  document that hangs cannot be stopped without killing the worker. That is more code for
  the same isolation.
- **Reading on Linux,** where #357 does not occur: the production path later, with the
  containerised deployment. Here the vision server runs on Windows, next to the GPU.

## Consequences

- **Cost:** each child loads Docling's models again. The first full run (28 September 2026:
  98 documents, 584 pages, Docling's own tables, no vision model) took 43 minutes, with
  0 failures:
  - one-page documents took 13.6–16 s, so about 13 s per document is model loading, roughly
    21 minutes of the run;
  - starting processes added another 4.6 minutes.

  Isolation therefore about doubles a full rebuild. If that ever matters, a child can read a
  batch of documents; the report and resumption stay the same.
- **The Kiwa BDA Agrément** (AES-encrypted) is read by Docling, but pypdf cannot open it
  without its cryptography extra, so its 11 pages are flagged "no text layer to check".
- `data/elements/` becomes the input to building passages. The index is rebuilt from saved
  readings without reading any PDF again.
- The report is the list of what to look at. Flagged pages are named with their cause, and
  none is dropped from the index: recovered lines keep every word.

## Update (29 September 2026)

The page check no longer uses pypdf's text layer. Each page is read by pdfium, and every
word is marked with whether a reader sees it (the page drawn with and without its text; see
the X8 report, "index only what the page shows"). Words Docling reads where no reader sees
them are removed from its elements. Visible words its reading lacks are recovered and placed
where they stand. Each page records the visible words, how many of them Docling's reading
holds, the words not shown, the hidden words removed and the lines recovered. The Kiwa BDA
Agrément is checked like any other document, because pdfium opens it. The reader's
fingerprint also covers `recovery.py` and `visibility.py`.

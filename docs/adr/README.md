# Decision records

Read these before proposing a change. Each record states what is settled and why;
**0031** lists every reading and retrieval decision since X42, including what was tried
and rejected. Records 0001–0025 are in the development repository
(`../lime-green-assistant/docs/adr/`).

| Record | Settles |
|---|---|
| [0026](0026-evolve-the-submission-into-the-platform.md) | The submission repository becomes the platform, built in place; tag `v5-baseline` is the reference |
| [0027](0027-read-pdfs-in-isolated-processes.md) | Each PDF read in its own process, with a fingerprint and a validation record (the reader itself: Docling layout, GLM-OCR tables, pdfium visibility) |
| [0028](0028-answer-path-after-e5.md) | The answer path after E5: whole lists, a scoped second search, fairer verification, no answerability gate |
| [0029](0029-generator-after-e8.md) | The generator: Gemma 4 26B-A4B, thinking off |
| [0030](0030-search-channels-after-x44.md) | Search channels: company content, pictures and guidance ranked apart |
| [0031](0031-every-data-type-settled-rejected-tuned.md) | Every data type after X42–X47: settled, rejected, still being tuned |
| [0032](0032-retrieval-frozen-for-e.md) | Retrieval frozen for E: one BM25 index per channel, a search per thing a part asks about |

Experiment reports with the full evidence are in `evaluation/reports/`.

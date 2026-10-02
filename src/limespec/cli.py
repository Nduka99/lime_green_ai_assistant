"""Command line: acquire collects the sources, ingest builds the index, ask answers
a question, serve runs the web page, and search shows what retrieval finds."""

import argparse
import json
import sys
from pathlib import Path

import psycopg
import uvicorn

from limespec import (
    acquire,
    assistant,
    config,
    documents,
    llm,
    store,
    telemetry,
    weights,
)
from limespec.app import app
from limespec.ingest import (
    PICTURE_VECTORS,
    WEB_FORMS,
    IngestError,
    cache_path,
    ingest,
    pdf_titles,
    site_html,
)
from limespec.passages import FORMS
from limespec.view import AnswerView, view


def run_acquire(what: str, measure_only: bool) -> None:
    """Pages from the sitemap not yet cached, the PDFs and images linked from
    cached pages, or the external documents listed in sources-external.txt, not yet
    stored; `measure_only` sizes them without downloading."""
    if what == "external":
        licences = acquire.read_external(config.EXTERNAL_SOURCES)
        if measure_only:
            stored = {record["url"] for record in acquire.read_manifest()}
            report(acquire.measure([url for url in licences if url not in stored]))
        else:
            report(acquire.acquire_files(list(licences), "external", licences=licences))
        return
    if what == "pages":
        pages = [url for url in acquire.sitemap_pages() if not cache_path(url).exists()]
        if measure_only:
            report(acquire.measure(pages))
        else:
            report(acquire.acquire_pages(pages))
        return
    documents, images = acquire.cached_links()
    if measure_only:
        stored = {record["url"] for record in acquire.read_manifest()}
        report(acquire.measure([u for u in documents + images if u not in stored]))
    else:
        report(
            acquire.acquire_files(documents, "document")
            + acquire.acquire_files(images, "image")
        )


def report(results: list[acquire.Record]) -> None:
    fine = [record for record in results if "error" not in record]
    sizes = [record["bytes"] for record in fine if record.get("bytes") is not None]
    print(f"{len(fine)} of {len(results)} fine, {sum(sizes) / 1e6:.1f} MB")
    for record in results:
        if "error" in record:
            print(f"  failed: {record['url']}: {record['error']}")


def run_ingest(
    sources: Path | None,
    live: bool,
    all_pages: bool = False,
    pdf_form: str = "",
    web_form: str = "",
    with_pictures: bool = False,
) -> None:
    found = []
    if pdf_form:
        found = documents.index_documents(pdf_form, pdf_titles(site_html()))
    with assistant.connect() as conn:
        version, manifest = ingest(
            conn,
            llm.embed,
            sources,
            live,
            all_pages,
            found,
            web_form,
            with_pictures,
        )
    if live:
        print(f"index version: {version} (live)")
    else:
        print(
            f"index version: {version} (not live; serve it with "
            f"LIMESPEC_INDEX_VERSION={version})"
        )
    for key, value in manifest.items():
        print(f"{key}: {value}")


def render_text(answer: AnswerView) -> str:
    """The answer as plain text, laid out like the brief's example: answer, sources."""
    lines = ["Answer:"]
    for number, claim in enumerate(answer["claims"], 1):
        refs = " ".join(f"[{source}]" for source in claim["sources"])
        lines.append(f"{number}. {claim['text']} {refs}")
    if answer["notice"]:
        if answer["claims"]:
            lines += ["", "Note:"]
        lines += answer["notice"].splitlines()
    if answer["sources"]:
        lines += ["", "Sources:"]
        for source in answer["sources"]:
            lines += [
                f"[{source['number']}] {source['title']} › {source['heading']} "
                f"(captured {source['captured']})",
                f'    "{source["quote"]}"',
                f"    {source['link']}",
            ]
    if answer["closest_pages"]:
        lines += ["", "Closest pages:"]
        lines += [
            f"- {page['title']}: {page['url']}" for page in answer["closest_pages"]
        ]
    return "\n".join(lines)


def run_ask(question: str | None) -> None:
    question = (question or input("Ask a question: ")).strip()
    if not question:
        print("No question asked.")
        return
    print(render_text(view(assistant.ask(question))))


def run_search(question: str) -> None:
    with assistant.connect() as conn:
        version = assistant.served_index(conn)
        passages = store.search(conn, version, question, llm.embed, llm.rerank)
    for rank, passage in enumerate(passages, start=1):
        print(f"{rank}. {passage.title} › {passage.heading}\n   {passage.url}")
        print(f"   {passage.text[:200]!r}")


def run_read_images(vlm: str, vectors: bool = False) -> int:
    """Store every picture of the pages and documents once, then read the text in
    each with a vision model (GLM-OCR at `vlm`, X43 B) and give each its SigLIP2
    vector (`vectors`, X44 F2); what is already saved is kept."""
    from PIL import Image

    from limespec import images, siglip

    if not vlm and not vectors:
        print("error: give --vlm, --vectors or both", file=sys.stderr)
        return 1
    if vlm and not llm.healthy(vlm):
        print(f"error: no vision model ready at {vlm}", file=sys.stderr)
        return 1
    readings = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(documents.OUT.glob("*.json"))
        if path.name != "report.json"
    ]
    stored = {}
    for record in acquire.read_manifest():
        path = acquire.store_path(record["sha256"])
        if record.get("content_type") == documents.WORD:
            path = documents.OUT / "rendered" / f"{record['sha256']}.pdf"  # laid out
        stored[record["url"]] = path
    places = images.collect(dict(site_html()), readings, stored, config.IMAGES)
    text = json.dumps(places, indent=1, ensure_ascii=False)
    (config.IMAGES / "places.json").write_text(text + "\n", encoding="utf-8")
    read = 0
    for identity in dict.fromkeys(place["id"] for place in places):
        target = config.IMAGES / f"{identity}.json"
        png = config.IMAGES / f"{identity}.png"
        saved = (
            json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        )
        saved["id"] = identity
        if vlm and "ocr" not in saved:
            with Image.open(png) as picture:
                saved["ocr"] = images.read_text(picture.convert("RGB"), vlm)
            read += 1
        target.write_text(json.dumps(saved), encoding="utf-8")
    ids = list(dict.fromkeys(place["id"] for place in places))
    made = 0
    if vectors:
        path = config.IMAGES / PICTURE_VECTORS
        known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        embed_pictures, _ = siglip.siglip_model(config.SIGLIP)
        found = siglip.picture_vectors(ids, config.IMAGES, embed_pictures, known)
        path.write_text(json.dumps(found), encoding="utf-8")
        made = len(set(found) - set(known))
    print(f"{len(places)} places of {len(ids)} pictures; {read} read and "
          f"{made} vectors made now")  # fmt: skip
    return 0


def run_read_pdfs(vlm: str) -> int:
    """Read every stored PDF; print the run's totals, failures and flagged pages."""
    if vlm and not llm.healthy(vlm):
        print(f"error: no vision model ready at {vlm}", file=sys.stderr)
        return 1
    files = documents.pdf_files(acquire.read_manifest())
    report = documents.run_all(files, vlm, documents.OUT)
    print(
        f"{len(files)} PDFs: {len(report['read'])} read, "
        f"{len(report['skipped'])} already read, {len(report['failed'])} failed"
    )
    for sha256, failure in report["failed"].items():
        print(f"  failed {failure['urls'][0]} ({sha256[:12]}): {failure['errors'][-1]}")
    for key, value in report["summary"]["totals"].items():
        print(f"{key}: {value:g}" if isinstance(value, float) else f"{key}: {value}")
    for page in report["summary"]["flagged"]:
        name = page["url"].rsplit("/", 1)[-1]
        print(f"  flagged {name} p{page['page']}: {', '.join(page['flags'])} "
              f"({page['kept']}/{page['words']} words, {page['grade']})")  # fmt: skip
    print(f"report: {documents.OUT / 'report.json'}")
    return 1 if report["failed"] else 0


def run_serve(port: int) -> None:
    # uvicorn logs the address once it is listening, or why it could not start. Its
    # access lines are off: request spans and metrics record every request, and the
    # page's query string would put questions in the log.
    uvicorn.run(
        app,
        host=config.APP_HOST,
        port=port,
        log_config=telemetry.LOG_CONFIG,
        access_log=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="limespec", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    acquire_parser = commands.add_parser(
        "acquire",
        help="collect sitemap pages, their PDFs and images, or external documents",
    )
    acquire_parser.add_argument("what", choices=["pages", "files", "external"])
    acquire_parser.add_argument(
        "--measure", action="store_true", help="only size them (HEAD requests)"
    )
    commands.add_parser(
        "browse", help="give the collected files readable names in data/browse/"
    )
    ingest_parser = commands.add_parser(
        "ingest", help="index the pages in sources.txt as a new live Postgres version"
    )
    ingest_parser.add_argument(
        "--sources", type=Path, help="a list of page URLs other than sources.txt"
    )
    ingest_parser.add_argument(
        "--no-live",
        dest="live",
        action="store_false",
        help="build the version beside the live one without serving it",
    )
    ingest_parser.add_argument(
        "--all-pages",
        action="store_true",
        help="every cached page of the site instead of sources.txt",
    )
    ingest_parser.add_argument(
        "--pdf-form",
        choices=FORMS,
        default="",
        help="add every saved PDF reading, its tables in this form (X9)",
    )
    ingest_parser.add_argument(
        "--web-form",
        choices=WEB_FORMS,
        default="",
        help="read the pages by limespec.webpage, passages in this form (X42 W3)",
    )
    ingest_parser.add_argument(
        "--images",
        action="store_true",
        help="add a passage per picture `read-images` stored and read (X43)",
    )
    ask_parser = commands.add_parser("ask", help="answer a question with its sources")
    ask_parser.add_argument("question", nargs="?", help="asked for if left out")
    serve_parser = commands.add_parser("serve", help="run the web page on this machine")
    serve_parser.add_argument("--port", type=int, default=config.APP_PORT)
    search_parser = commands.add_parser("search", help="show the passages retrieved")
    search_parser.add_argument("question")
    read_parser = commands.add_parser(
        "read-pdfs",
        help="read every stored PDF into elements, each in its own process "
        "(needs the ingest group)",
    )
    read_parser.add_argument(
        "--vlm", default="", help="a vision model server that reads tables again"
    )
    images_parser = commands.add_parser(
        "read-images",
        help="store every picture once and read its text (needs the ingest group)",
    )
    images_parser.add_argument("--vlm", default="", help="GLM-OCR's server")
    images_parser.add_argument(
        "--vectors", action="store_true", help="each picture's SigLIP2 vector (X44 F2)"
    )
    one_parser = commands.add_parser(
        "read-pdf", help="read one stored PDF into a JSON file (used by read-pdfs)"
    )
    one_parser.add_argument("sha256")
    one_parser.add_argument("out", type=Path)
    one_parser.add_argument("--vlm", default="")
    models_parser = commands.add_parser(
        "models", help="check the files in models/ against models.json"
    )
    models_parser.add_argument(
        "--quick", action="store_true", help="compare sizes only, not SHA-256"
    )
    args = parser.parse_args(argv)
    if args.command == "read-pdfs":
        return run_read_pdfs(args.vlm)
    if args.command == "read-images":
        return run_read_images(args.vlm, args.vectors)
    if args.command == "read-pdf":
        reading = documents.read_one(args.sha256, args.vlm)
        text = json.dumps(reading, indent=1, ensure_ascii=False) + "\n"
        args.out.write_text(text, encoding="utf-8", newline="\n")
        return 0
    if args.command == "models":
        entries = weights.read()
        found = weights.problems(entries, weights.FOLDER, args.quick)
        for problem in found:
            print(problem)
        print(f"{len(entries)} model files checked, {len(found)} problems")
        return 1 if found else 0
    try:
        if args.command == "acquire":
            run_acquire(args.what, args.measure)
        elif args.command == "browse":
            made = acquire.browse()
            print(f"{made} new readable names in {config.FILE_STORE.parent / 'browse'}")
        elif args.command == "ingest":
            run_ingest(
                args.sources,
                args.live,
                args.all_pages,
                args.pdf_form,
                args.web_form,
                args.images,
            )
        elif args.command == "ask":
            run_ask(args.question)
        elif args.command == "serve":
            run_serve(args.port)
        else:
            run_search(args.question)
    except (IngestError, llm.ModelServerError, psycopg.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0

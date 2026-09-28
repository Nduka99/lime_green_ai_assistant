"""Command line: acquire collects the sources, ingest builds the index, ask answers
a question, serve runs the web page, and search shows what retrieval finds."""

import argparse
import sys

import psycopg
import uvicorn

from limespec import acquire, assistant, config, llm, store, telemetry
from limespec.app import app
from limespec.ingest import IngestError, cache_path, ingest
from limespec.view import AnswerView, view


def run_acquire(what: str, measure_only: bool) -> None:
    """Pages from the sitemap not yet cached, or the PDFs and images linked from
    cached pages not yet stored; `measure_only` sizes them without downloading."""
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


def run_ingest() -> None:
    with assistant.connect() as conn:
        version, manifest = ingest(conn, llm.embed)
    print(f"index version: {version} (live)")
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
        version = assistant.live_index(conn)
        passages = store.search(conn, version, question, llm.embed, llm.rerank)
    for rank, passage in enumerate(passages, start=1):
        print(f"{rank}. {passage.title} › {passage.heading}\n   {passage.url}")
        print(f"   {passage.text[:200]!r}")


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
        "acquire", help="collect sitemap pages, or the PDFs and images they link"
    )
    acquire_parser.add_argument("what", choices=["pages", "files"])
    acquire_parser.add_argument(
        "--measure", action="store_true", help="only size them (HEAD requests)"
    )
    commands.add_parser(
        "ingest", help="index the pages in sources.txt as a new live Postgres version"
    )
    ask_parser = commands.add_parser("ask", help="answer a question with its sources")
    ask_parser.add_argument("question", nargs="?", help="asked for if left out")
    serve_parser = commands.add_parser("serve", help="run the web page on this machine")
    serve_parser.add_argument("--port", type=int, default=config.APP_PORT)
    search_parser = commands.add_parser("search", help="show the passages retrieved")
    search_parser.add_argument("question")
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            run_acquire(args.what, args.measure)
        elif args.command == "ingest":
            run_ingest()
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

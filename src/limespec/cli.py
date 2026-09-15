"""Command line: ingest builds the index, ask answers a question, serve runs the
web page, and search shows what retrieval finds."""

import argparse
import sys
from contextlib import closing

import uvicorn

from limespec import assistant, config, llm
from limespec.app import app
from limespec.ingest import IngestError, ingest
from limespec.retrieve import search
from limespec.view import AnswerView, view


def run_ingest() -> None:
    manifest = ingest(llm.embed)
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
    with closing(assistant.open_index()) as conn:
        passages = search(conn, question, llm.embed, llm.rerank)
    for rank, passage in enumerate(passages, start=1):
        print(f"{rank}. {passage.title} › {passage.heading}\n   {passage.url}")
        print(f"   {passage.text[:200]!r}")


def run_serve(port: int) -> None:
    # uvicorn prints the address once it is listening, or why it could not start.
    uvicorn.run(app, host=config.APP_HOST, port=port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="limespec", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="fetch the pages in sources.txt and index them")
    ask_parser = commands.add_parser("ask", help="answer a question with its sources")
    ask_parser.add_argument("question", nargs="?", help="asked for if left out")
    serve_parser = commands.add_parser("serve", help="run the web page on this machine")
    serve_parser.add_argument("--port", type=int, default=config.APP_PORT)
    search_parser = commands.add_parser("search", help="show the passages retrieved")
    search_parser.add_argument("question")
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            run_ingest()
        elif args.command == "ask":
            run_ask(args.question)
        elif args.command == "serve":
            run_serve(args.port)
        else:
            run_search(args.question)
    except (IngestError, llm.ModelServerError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0

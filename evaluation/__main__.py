"""The harness command line. Run from the repository root:

    uv run python -m evaluation verify                       # every set's hashes
    uv run python -m evaluation register SET --description "..."
    uv run python -m evaluation check-key SET --seed N --prefix v4q
    uv run python -m evaluation retrieval SET                # saved TREC runs
    uv run python -m evaluation grades SET SITTING           # a grading sitting
    uv run python -m evaluation guardrails SET ANSWERS.json  # prices, emergencies
    uv run --group ingest python -m evaluation parsing x8-pages --out DIR  # X8
    uv run python -m evaluation sample-pages --catalogue data/catalogue.json \
        --seed 9 --exclude-set x8-pages --out FILE [--blank 6]   # X8's pages
    uv run python -m evaluation ask SET --target URL --run NAME        # the v1 API
    uv run python -m evaluation ask SET --target URL --run v5 --endpoint /api/answer
    uv run python -m evaluation catalogue --out data/catalogue.json   # source strata
    uv run python -m evaluation check-conversations KEY.json ... --plan PLAN.json \
        [--out data/eval/SET/key.json]           # writes the whole key when clean
    uv run python -m evaluation blind SET FIRST.json SECOND.json --seed N --out DIR
    uv run python -m evaluation unblind SET FIRST.json SECOND.json --dir DIR

Sets live in git-ignored data/eval/, and `ask` saves to git-ignored data/runs/.
A finished run is graded, then copied into a sitting folder of its set and
registered, so the evidence behind every reported number is hashed. Two runs are
compared by `blind`, which writes the answers that differ for blind grading into
DIR/pairs.json, and `unblind`, which reads the verdicts from DIR/verdicts.json.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader

from evaluation import (
    ask,
    catalogue,
    conversations,
    grades,
    guardrails,
    keys,
    pages,
    pairs,
    parsing,
    retrieval,
    sets,
)
from limespec import acquire, pdf

ANSWER_TIMEOUT_SECONDS = 600.0  # an answer on the laptop can take minutes


def page_reader(folder: Path) -> keys.ReadPage:
    """Cached pages by URL, named as `limespec ingest` names them."""

    def read(url: str) -> str | None:
        slug = urlsplit(url).path.strip("/").replace("/", "__") or "home"
        path = folder / f"{slug}.html"
        return path.read_text(encoding="utf-8") if path.exists() else None

    return read


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="python -m evaluation", description=__doc__)
    main.add_argument("--root", type=Path, default=sets.ROOT)
    main.add_argument("--registry", type=Path, default=sets.REGISTRY)
    main.add_argument("--runs", type=Path, default=Path("data/runs"))
    commands = main.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="check registered hashes")
    verify.add_argument("names", nargs="*", help="sets to check (default: all)")
    register = commands.add_parser("register", help="hash a set's new files")
    register.add_argument("name")
    register.add_argument("--description", default="")
    check = commands.add_parser("check-key", help="check a key, write blind questions")
    check.add_argument("name")
    check.add_argument("--seed", type=int, required=True)
    check.add_argument("--prefix", required=True)
    check.add_argument("--pages", type=Path, default=Path("data/site"))
    scored = commands.add_parser("retrieval", help="score saved retrieval runs")
    scored.add_argument("name")
    scored.add_argument("--json", action="store_true")
    listed = commands.add_parser(
        "catalogue", help="label every collected source by format and topic"
    )
    listed.add_argument("--out", type=Path, required=True, help="a JSON file to write")
    planned = commands.add_parser(
        "plan-conversations", help="plan a conversation key and write its bundle"
    )
    planned.add_argument("--catalogue", type=Path, required=True)
    planned.add_argument("--brief", type=Path, required=True)
    planned.add_argument("--out", type=Path, required=True)
    planned.add_argument("--seed", type=int, required=True)
    planned.add_argument("--conversations", type=int, default=20)
    planned.add_argument(
        "--turns", type=int, default=4, help="sources per conversation"
    )
    planned.add_argument("--per-part", type=int, default=5)
    planned.add_argument(
        "--limit", type=int, default=8000, help="characters per source"
    )
    written = commands.add_parser(
        "check-conversations", help="check a conversation key against its bundle"
    )
    written.add_argument("keys", nargs="+", type=Path, help="the key's JSON files")
    written.add_argument(
        "--plan", type=Path, required=True, help="the bundle's plan.json"
    )
    written.add_argument(
        "--out", type=Path, help="write the whole key here if it has no problems"
    )
    guarded = commands.add_parser(
        "guardrails", help="check a run for shown prices and missed emergencies"
    )
    guarded.add_argument("name")
    guarded.add_argument("answers", type=Path, help="a run's answers file")
    parsed = commands.add_parser(
        "parsing", help="score the PDF parsers against a page set's truth (X8)"
    )
    parsed.add_argument("name")
    parsed.add_argument(
        "--out", type=Path, required=True, help="where each parser's output is saved"
    )
    parsed.add_argument("--json", action="store_true")
    sampled = commands.add_parser(
        "sample-pages", help="draw PDF pages for X8 from the catalogue, by code"
    )
    sampled.add_argument("--catalogue", type=Path, required=True)
    sampled.add_argument("--seed", type=int, required=True)
    sampled.add_argument(
        "--exclude-set", help="a page set whose documents and pages are left out"
    )
    sampled.add_argument(
        "--exclude", nargs="*", default=[], help="document ids to leave out"
    )
    sampled.add_argument(
        "--blank", type=int, default=0, help="also draw this many pages without text"
    )
    sampled.add_argument("--out", type=Path, required=True, help="a JSON file")
    graded = commands.add_parser("grades", help="count a grading sitting's verdicts")
    graded.add_argument("name")
    graded.add_argument("sitting")
    graded.add_argument("--json", action="store_true")
    asked = commands.add_parser("ask", help="ask a set through a deployed endpoint")
    asked.add_argument("name")
    asked.add_argument("--target", required=True, help="e.g. http://127.0.0.1:8090")
    asked.add_argument(
        "--endpoint",
        default="/api/v1/answers",
        help="/api/answer for the submitted v5 (default: the v1 API)",
    )
    asked.add_argument("--run", required=True, help="a name for this run's file")
    hidden = commands.add_parser("blind", help="write two runs' different answers")
    hidden.add_argument("name")
    hidden.add_argument("first", type=Path, help="the baseline run's answers file")
    hidden.add_argument("second", type=Path, help="the candidate run's answers file")
    hidden.add_argument("--seed", type=int, required=True)
    hidden.add_argument("--out", type=Path, required=True)
    shown = commands.add_parser("unblind", help="compare two runs from blind verdicts")
    shown.add_argument("name")
    shown.add_argument("first", type=Path)
    shown.add_argument("second", type=Path)
    shown.add_argument("--dir", type=Path, required=True)
    shown.add_argument("--json", action="store_true")
    return main


def run_verify(args: argparse.Namespace) -> int:
    names = args.names or list(sets.read_registry(args.registry)["sets"])
    found = [p for name in names for p in sets.problems(name, args.root, args.registry)]
    for problem in found:
        print("PROBLEM", problem)
    print(f"{len(names)} sets checked, {len(found)} problems")
    return 1 if found else 0


def run_check_key(args: argparse.Namespace) -> int:
    folder = args.root / args.name
    key = grades.read_json(folder / "key.json")
    found, missing = keys.problems(key, page_reader(args.pages))
    wordings = sum(len(case.get("wordings", [])) for case in key.get("cases", []))
    print(f"{len(key.get('cases', []))} cases, {wordings} wordings")
    for problem in found:
        print("PROBLEM", problem)
    for url in sorted(missing):
        print("NOT CACHED", url)
    blind = folder / "questions.json"
    if found or missing or blind.exists():
        # A quote on an uncached page is unchecked, so the key cannot be sealed yet.
        print("blind file not written: fix the key, cache its pages, or it exists")
        return 1
    rows = keys.blind_questions(key, args.seed, args.prefix)
    text = json.dumps({"questions": rows}, indent=1, ensure_ascii=False) + "\n"
    blind.write_text(text, encoding="utf-8", newline="\n")
    print(f"blind file written: {blind} ({len(rows)} questions)")
    return 0


def run_retrieval(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    result = retrieval.score(retrieval.load(folder / "retrieval"))
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(retrieval.markdown(result, args.name))
    return 0


def run_catalogue(args: argparse.Namespace) -> int:
    entries = catalogue.catalogue()
    ask.write_records(args.out, entries)
    for label, count in catalogue.strata(entries).items():
        print(f"{count:5}  {label}")
    print(f"{len(entries)} sources labelled in {args.out}")
    return 0


def run_plan_conversations(args: argparse.Namespace) -> int:
    entries = grades.read_json(args.catalogue)
    texts = {entry["id"]: conversations.source_text(entry) for entry in entries}
    planned = conversations.plan(
        entries, texts, args.conversations, args.turns, args.seed
    )
    brief = args.brief.read_text(encoding="utf-8")
    parts = conversations.bundle(
        planned, entries, texts, brief, args.out, args.per_part, args.limit, args.seed
    )
    by_id = {entry["id"]: entry for entry in entries}
    used = [by_id[source]["format"] for c in planned for source in c["sources"]]
    for label in sorted(set(used)):
        print(f"{used.count(label):5}  {label}")
    print(
        f"{len(planned)} conversations, {len(used)} sources, "
        f"{len(parts)} parts in {args.out}"
    )
    return 0


def run_check_conversations(args: argparse.Namespace) -> int:
    seen = grades.read_json(args.plan)
    written = [c for path in args.keys for c in grades.read_json(path)["conversations"]]
    found = conversations.key_problems({"conversations": written}, seen)
    for problem in found:
        print("PROBLEM", problem)
    turns = sum(len(c.get("turns", [])) for c in written)
    later = [t for c in written for t in c.get("turns", [])[1:]]
    leaning = sum(t.get("standalone") is False for t in later)
    print(f"{len(written)} conversations, {turns} turns, {len(found)} problems")
    print(f"{leaning} of {len(later)} later turns lean on earlier turns")
    if found:
        return 1
    if args.out:
        if args.out.exists():
            # A key written into a set is sealed by its hash, so it is never replaced.
            print(f"key not written: {args.out} exists")
            return 1
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"conversations": written}, indent=1, ensure_ascii=False)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"key written: {args.out}")
    return 0


def run_guardrails(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    records = {r["id"]: r for r in grades.read_json(args.answers)}
    result = guardrails.check(key, questions, records)
    print(guardrails.text(result))
    return 0 if guardrails.passed(result) else 1


def text_layer(path: Path, page: int) -> str:
    """One page of the PDF's text layer, as indexed before Docling."""
    return PdfReader(path).pages[page - 1].extract_text() or ""


def run_parsing(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    truth = grades.read_json(folder / "truth.json")["pages"]
    scores: dict[str, list[dict[str, Any]]] = {"pypdf": [], "docling": []}
    seconds = []
    saved = {}
    for page in truth:
        path = acquire.store_path(page["entry"].split(":", 1)[1])
        reference = text_layer(path, page["page"])
        started = time.perf_counter()
        found = [
            element
            for element in pdf.read_pdf(path, page["page"], page["page"])
            if element.page == page["page"]
        ]
        seconds.append(time.perf_counter() - started)
        units = [element.text for element in found if element.text]
        rows = [element.cells for element in found if element.kind == "table_row"]
        lines = reference.splitlines()
        scores["pypdf"].append(parsing.score_page(page, lines, [], reference))
        scores["docling"].append(parsing.score_page(page, units, rows, reference))
        saved[str(page["number"])] = {
            "pypdf": lines,
            "docling": [asdict(element) for element in found],
        }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("parsed.json", saved), ("scores.json", scores)):
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    result = parsing.summarise(scores, seconds)
    print(json.dumps(result, indent=1) if args.json else parsing.markdown(result))
    return 0 if all(result["gate"].values()) else 1


def run_sample_pages(args: argparse.Namespace) -> int:
    entries = grades.read_json(args.catalogue)
    read = cache(pages.read_pages)
    exclude = list(args.exclude)
    seen = []
    if args.exclude_set:
        folder = sets.require(args.exclude_set, args.root, args.registry)
        for page in grades.read_json(folder / "truth.json")["pages"]:
            exclude.append(page["entry"])
            source = str(acquire.store_path(page["entry"].split(":", 1)[1]))
            seen.append(read(source)[page["page"] - 1])
    drawn = {
        "pages": pages.sample(entries, read, args.seed, exclude, seen),
        "blank": pages.blank(entries, read, args.seed, args.blank),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(drawn, indent=1, ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    for page in drawn["pages"] + drawn["blank"]:
        name = page["url"].rsplit("/", 1)[-1]
        print(f"{page['format']:16} p{page['page']:<3} {name}")
    print(f"{len(drawn['pages'])} pages, {len(drawn['blank'])} blank, in {args.out}")
    return 0


def run_grades(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    graded, answers = grades.load_sitting(folder / args.sitting)
    result = grades.score(key, questions, graded, answers)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(grades.markdown(result, f"{args.name} · {args.sitting}"))
    return 0


def load_runs(first: Path, second: Path) -> dict[str, pairs.Records]:
    """Two answers files by run name (the file name without "answers-")."""
    runs = {}
    for path in (first, second):
        records = grades.read_json(path)
        runs[path.stem.removeprefix("answers-")] = {r["id"]: r for r in records}
    if len(runs) != 2:
        raise ValueError("the two runs need different file names")
    return runs


def run_blind(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    questions = grades.read_json(folder / "questions.json")["questions"]
    runs = load_runs(args.first, args.second)
    first, second = runs.values()
    ids = pairs.differing(first, second, [row["id"] for row in questions])
    blinded, order = pairs.blind(ids, runs, args.seed)
    ask.write_records(args.out / "pairs.json", blinded)
    (args.out / "order.json").write_text(json.dumps(order, indent=1), encoding="utf-8")
    print(f"{len(ids)} of {len(questions)} answers differ; pairs in {args.out}")
    return 0


def run_unblind(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    runs = load_runs(args.first, args.second)
    order = grades.read_json(args.dir / "order.json")
    if not (args.dir / "verdicts.json").exists():
        raise ValueError(f"grade the pairs first: no verdicts.json in {args.dir}")
    verdicts = grades.read_json(args.dir / "verdicts.json")
    if set(verdicts) != set(order):
        raise ValueError("verdicts.json must grade every pair in pairs.json")
    result = pairs.compare(key, questions, runs, pairs.unblind(verdicts, order))
    print(json.dumps(result, indent=1) if args.json else pairs.markdown(result))
    return 0


def run_ask(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    questions = grades.read_json(folder / "questions.json")["questions"]
    out = args.runs / args.name / f"answers-{args.run}.json"
    with httpx.Client(base_url=args.target, timeout=ANSWER_TIMEOUT_SECONDS) as client:
        records = ask.ask_all(questions, client, args.endpoint, out)
    errors = sum("view" not in record for record in records)
    print(f"{len(records)} answers saved to {out}, {errors} errors")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "verify":
            return run_verify(args)
        if args.command == "register":
            added = sets.register(args.name, args.description, args.root, args.registry)
            print(f"{args.name}: {len(added)} files registered")
            return 0
        if args.command == "check-key":
            return run_check_key(args)
        if args.command == "retrieval":
            return run_retrieval(args)
        if args.command == "catalogue":
            return run_catalogue(args)
        if args.command == "plan-conversations":
            return run_plan_conversations(args)
        if args.command == "check-conversations":
            return run_check_conversations(args)
        if args.command == "grades":
            return run_grades(args)
        if args.command == "guardrails":
            return run_guardrails(args)
        if args.command == "parsing":
            return run_parsing(args)
        if args.command == "sample-pages":
            return run_sample_pages(args)
        if args.command == "blind":
            return run_blind(args)
        if args.command == "unblind":
            return run_unblind(args)
        return run_ask(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

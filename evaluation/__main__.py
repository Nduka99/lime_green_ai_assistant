"""The harness command line. Run from the repository root:

    uv run python -m evaluation verify                       # every set's hashes
    uv run python -m evaluation register SET --description "..."
    uv run python -m evaluation check-key SET --seed N --prefix v4q
    uv run python -m evaluation retrieval SET                # saved TREC runs
    uv run python -m evaluation grades SET SITTING           # a grading sitting
    uv run python -m evaluation ask SET --target http://127.0.0.1:8090 --run v5

Sets live in git-ignored data/eval/, and `ask` saves to git-ignored data/runs/.
A finished run is graded, then copied into a sitting folder of its set and
registered, so the evidence behind every reported number is hashed.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from evaluation import ask, grades, keys, retrieval, sets

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
    graded = commands.add_parser("grades", help="count a grading sitting's verdicts")
    graded.add_argument("name")
    graded.add_argument("sitting")
    graded.add_argument("--json", action="store_true")
    asked = commands.add_parser("ask", help="ask a set through a deployed endpoint")
    asked.add_argument("name")
    asked.add_argument("--target", required=True, help="e.g. http://127.0.0.1:8090")
    asked.add_argument("--endpoint", default="/api/answer")
    asked.add_argument("--run", required=True, help="a name for this run's file")
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
        if args.command == "grades":
            return run_grades(args)
        return run_ask(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

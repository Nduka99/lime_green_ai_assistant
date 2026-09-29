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
    uv run python -m evaluation table-questions --out data/eval/x9-tables/questions.json
    uv run --env-file .env python -m evaluation quote-retrieval --version N --out FILE
    uv run python -m evaluation select-form table=FILE rows=FILE both=FILE page=FILE
    uv run --env-file .env python -m evaluation coverage conv-v1 --version N  # X36
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
from collections import Counter
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
    lookups,
    pages,
    pairs,
    parsing,
    retrieval,
    sets,
)
from limespec import acquire, assistant, config, ingest, llm, pdf, store, tables
from limespec.models import Passage

ANSWER_TIMEOUT_SECONDS = 600.0  # an answer on the laptop can take minutes
X8_SETS = ("x8-pages", "x8-pages-r2", "x8-pages-r3")  # sealed truth with tables


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
    parsed.add_argument("--arm", default="docling", help="a name for this arm")
    parsed.add_argument(
        "--vlm", default="", help="a vision model server that reads each table again"
    )
    transcribed = commands.add_parser(
        "transcription", help="score a vision model on a page set's blank pages (X8)"
    )
    transcribed.add_argument("name")
    transcribed.add_argument("--vlm", required=True, help="the model server's URL")
    transcribed.add_argument("--prompt", required=True, help="e.g. 'OCR:'")
    transcribed.add_argument("--out", type=Path, required=True)
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
    listed_pages = commands.add_parser(
        "page-candidates", help="list unused PDF pages in a seeded order (X8 round 3)"
    )
    listed_pages.add_argument("--catalogue", type=Path, required=True)
    listed_pages.add_argument("--seed", type=int, required=True)
    listed_pages.add_argument(
        "--exclude-set", action="append", default=[], help="a page set already used"
    )
    listed_pages.add_argument("--out", type=Path, required=True, help="a JSON file")
    questioned = commands.add_parser(
        "table-questions", help="write X9's table lookups from the X8 truth grids"
    )
    questioned.add_argument("--out", type=Path, required=True, help="a JSON file")
    searched = commands.add_parser(
        "quote-retrieval", help="score an index version's search on X9's evidence"
    )
    searched.add_argument("--version", type=int, required=True)
    searched.add_argument("--out", type=Path, required=True, help="a JSON file")
    covered = commands.add_parser(
        "coverage", help="count the answerable follow-ups an index version covers (X36)"
    )
    covered.add_argument("name")
    covered.add_argument("--version", type=int, required=True)
    selected = commands.add_parser(
        "select-form", help="compare X9's arms and apply its selection rule"
    )
    selected.add_argument("runs", nargs="+", help="ARM=FILE, the baseline arm table")
    rendered = commands.add_parser(
        "render-page", help="render one PDF page to a PNG (one page per process)"
    )
    rendered.add_argument("source", type=Path, help="the PDF")
    rendered.add_argument("page", type=int)
    rendered.add_argument("out", type=Path, help="the PNG to write")
    rendered.add_argument("--scale", type=float, default=2.0, help="2 = 144 DPI")
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
    scores: dict[str, list[dict[str, Any]]] = {"pypdf": [], args.arm: []}
    seconds = []
    saved = {}
    stats: Counter[str] = Counter()
    for page in truth:
        path = acquire.store_path(page["entry"].split(":", 1)[1])
        reference = text_layer(path, page["page"])
        started = time.perf_counter()
        found = [
            element
            for element in pdf.read_pdf(
                path, page["page"], page["page"], args.vlm, stats
            )
            if element.page == page["page"]
        ]
        seconds.append(time.perf_counter() - started)
        # A whole table repeats its rows' text, so it is measured by its grid only.
        units = [e.text for e in found if e.text and e.kind != "table"]
        rows = [element.cells for element in found if element.kind == "table_row"]
        grids = [element.grid for element in found if element.kind == "table"]
        lines = reference.splitlines()
        scores["pypdf"].append(parsing.score_page(page, lines, [], reference))
        scores[args.arm].append(parsing.score_page(page, units, rows, reference, grids))
        saved[str(page["number"])] = {
            "pypdf": lines,
            args.arm: [asdict(element) for element in found],
        }
    result = parsing.summarise(scores, seconds, args.arm)
    result["tables"] = dict(stats)
    args.out.mkdir(parents=True, exist_ok=True)
    outputs = (("parsed.json", saved), ("scores.json", scores), ("result.json", result))
    for name, data in outputs:
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=1) if args.json else parsing.markdown(result))
    return 0 if all(result["gate"].values()) else 1


def run_transcription(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    blank = grades.read_json(folder / "truth.json")["blank"]
    answers = {}
    counts: Counter[str] = Counter()
    for page in blank:
        path = acquire.store_path(page["entry"].split(":", 1)[1])
        image = pdf.page_image(path, page["page"], pdf.IMAGES_SCALE)
        answer = tables.recognise(image, args.vlm, args.prompt)
        scored = parsing.transcription(page["words"], answer)
        answers[page["number"]] = {"answer": answer, **scored}
        for measure, (found, total) in scored.items():
            counts[f"{measure} found"] += found
            counts[f"{measure} total"] += total
    shares = {
        measure: counts[f"{measure} found"] / max(counts[f"{measure} total"], 1)
        for measure in parsing.TRANSCRIPTION
    }
    args.out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        {"pages": answers, "pooled": shares}, indent=1, ensure_ascii=False
    )
    (args.out / "transcription.json").write_text(text + "\n", encoding="utf-8")
    passed = all(shares[m] >= bar for m, bar in parsing.TRANSCRIPTION.items())
    for measure, bar in parsing.TRANSCRIPTION.items():
        print(f"{measure}: {shares[measure]:.3f} (bar {bar})")
    print("pass" if passed else "FAIL")
    return 0 if passed else 1


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


def run_page_candidates(args: argparse.Namespace) -> int:
    entries = grades.read_json(args.catalogue)
    read = cache(pages.read_pages)
    used = set()
    seen = []
    for name in args.exclude_set:
        folder = sets.require(name, args.root, args.registry)
        truth = grades.read_json(folder / "truth.json")
        for page in truth["pages"] + truth.get("blank", []):
            used.add((page["entry"], page["page"]))
            source = str(acquire.store_path(page["entry"].split(":", 1)[1]))
            seen.append(read(source)[page["page"] - 1])
    found = pages.candidates(entries, read, args.seed, used, seen)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(found, indent=1, ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(found)} candidate pages in {args.out}")
    return 0


def write_json(path: Path, data: Any) -> None:
    """Plain data as readable UTF-8 JSON, its folder made if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def run_table_questions(args: argparse.Namespace) -> int:
    titles = ingest.pdf_titles(ingest.site_html())
    items = []
    for name in X8_SETS:
        folder = sets.require(name, args.root, args.registry)
        truth = grades.read_json(folder / "truth.json")["pages"]
        items += lookups.table_questions(name, truth, titles)
    write_json(args.out, {"questions": items})
    for name, count in Counter(item["cluster"].split("/")[0] for item in items).items():
        print(f"{count:5}  {name}")
    print(f"{len(items)} table lookups in {args.out}")
    return 0


def reading_urls() -> dict[str, str]:
    """Each saved PDF reading's file SHA-256 and the URL the index files it under."""
    found = {}
    for path in sorted(config.READINGS.glob("*.json")):
        if path.name == "report.json":
            continue
        reading = json.loads(path.read_text(encoding="utf-8"))
        found[str(reading["sha256"])] = str(reading["urls"][0])
    return found


def run_quote_retrieval(args: argparse.Namespace) -> int:
    urls = reading_urls()
    lookup_set = sets.require("x9-tables", args.root, args.registry)
    conversation_set = sets.require("conv-v1", args.root, args.registry)
    items = grades.read_json(lookup_set / "questions.json")["questions"]
    items += lookups.quote_items(
        grades.read_json(conversation_set / "key.json"),
        grades.read_json(conversation_set / "plan.json"),
        set(urls),
    )
    results = []
    anywhere: dict[str, list[Passage]] = {}
    with assistant.connect() as conn:
        for item in items:
            url = urls[item["sha256"]]
            if url not in anywhere:
                anywhere[url] = store.document_passages(conn, args.version, url)
            ranked = store.search(
                conn, args.version, item["question"], llm.embed, llm.rerank
            )
            results.append(lookups.score_item(item, ranked, anywhere[url], url))
        passages = store.passage_count(conn, args.version)
    found = lookups.summary(results)
    record = {"version": args.version, "passages": passages, "summary": found}
    write_json(args.out, {**record, "results": results})
    for name, scores in found.items():
        print(
            f"{name}: {scores['count']:.0f} items, Success@{lookups.TOP} "
            f"{scores['success']:.3f}, MRR {scores['mrr']:.3f}, "
            f"ceiling {scores['ceiling']:.3f}"
        )
    print(f"{passages} passages in version {args.version}; results in {args.out}")
    return 0


def run_coverage(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    plan = grades.read_json(folder / "plan.json")
    with assistant.connect() as conn:
        texts = store.searchable_texts(conn, args.version)
    found = conversations.coverage(key, texts)
    formats = {entry["id"]: entry["format"] for entry in catalogue.catalogue()}
    turns = {turn["id"]: turn for c in key["conversations"] for turn in c["turns"]}
    kinds: Counter[str] = Counter()
    for turn_id in found["missing"]:
        for part in turns[turn_id]["parts"]:
            for evidence in part["evidence"]:
                entry = plan["sources"][evidence["source"]]["entry"]
                kinds[formats.get(entry, "unknown")] += 1
    print(
        f"{found['covered']} of {found['follow_ups']} answerable follow-ups in scope "
        f"in version {args.version}"
    )
    for name, count in kinds.most_common():
        print(f"{count:5}  quotes of uncovered turns from {name}")
    return 0


def run_select_form(args: argparse.Namespace) -> int:
    arms = {}
    for run in args.runs:
        name, _, path = run.partition("=")
        arms[name] = grades.read_json(Path(path))
    if lookups.BASELINE not in arms:
        raise ValueError(f"no run for the baseline arm {lookups.BASELINE!r}")
    baseline = arms[lookups.BASELINE]["results"]
    print("| arm | passages | lookups S@8 (vs table) | conv-v1 S@8 (vs table) |")
    print("|---|---|---|---|")
    for name, arm in arms.items():
        cells = []
        for set_name in ("x9-tables", "conv-v1"):
            score = arm["summary"][set_name]["success"]
            change = lookups.compare(arm["results"], baseline, set_name)
            cells.append(
                f"{score:.3f} ({change['difference']:+.3f} "
                f"[{change['low']:+.3f}, {change['high']:+.3f}])"
            )
        print(f"| {name} | {arm['passages']} | {cells[0]} | {cells[1]} |")
    print(f"selected: {lookups.select(arms)}")
    return 0


def run_render_page(args: argparse.Namespace) -> int:
    image = pdf.page_image(args.source, args.page, args.scale)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(f"{args.out}: {image.width} x {image.height}")
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
        if args.command == "transcription":
            return run_transcription(args)
        if args.command == "render-page":
            return run_render_page(args)
        if args.command == "table-questions":
            return run_table_questions(args)
        if args.command == "quote-retrieval":
            return run_quote_retrieval(args)
        if args.command == "select-form":
            return run_select_form(args)
        if args.command == "coverage":
            return run_coverage(args)
        if args.command == "page-candidates":
            return run_page_candidates(args)
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

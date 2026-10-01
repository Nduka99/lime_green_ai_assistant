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
    uv run python -m evaluation replace-cases BUNDLE v4c53 --catalogue FILE --seed N \
        --part 5                              # new sources for flagged cases
    uv run python -m evaluation table-questions --out data/eval/x9-tables/questions.json
    uv run --env-file .env python -m evaluation quote-retrieval --version N --out FILE
    uv run python -m evaluation select-form table=FILE rows=FILE both=FILE page=FILE
    uv run --env-file .env python -m evaluation coverage conv-v1 --version N  # X36
    uv run --env-file .env python -m evaluation reach SET RUN.json  # evidence given
    uv run --env-file .env python -m evaluation replay SET --version N --out FILE \
        [--parts EARLIER.json]        # searches only, scored by reach (E5)
    uv run python -m evaluation unblind SET FIRST.json SECOND.json --dir DIR
    uv run --env-file .env python -m evaluation replay-requests RUN.json ... --out F
    uv run --env-file .env python -m evaluation generator-pass URL REQUESTS.json \
        --out PASS.json [--pid N] [--cache-prompt] [--concurrency 2]  # X39/X41
    uv run python -m evaluation generator-compare KEPT.json STEP.json --noise A B

Sets live in git-ignored data/eval/, and `ask` saves to git-ignored data/runs/.
A finished run is graded, then copied into a sitting folder of its set and
registered, so the evidence behind every reported number is hashed. Two runs are
compared by `blind`, which writes the answers that differ for blind grading into
DIR/pairs.json, and `unblind`, which reads the verdicts from DIR/verdicts.json.
"""

import argparse
import json
import shutil
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
    abstainer,
    ask,
    candidates,
    cases,
    catalogue,
    claims,
    conversations,
    detectors,
    docxpages,
    drafts,
    generator,
    graders,
    grades,
    guardrails,
    imagesets,
    keys,
    lookups,
    nearmiss,
    pages,
    pairs,
    parsing,
    reach,
    relevance,
    reliability,
    replay,
    retrieval,
    sets,
    slotbench,
    support,
    versions,
    webpages,
)
from limespec import (
    acquire,
    answer,
    assistant,
    config,
    images,
    ingest,
    layout,
    llm,
    office,
    pdf,
    scope,
    store,
    tables,
    verify,
    webpage,
)
from limespec.models import Passage, described

ANSWER_TIMEOUT_SECONDS = 600.0  # an answer on the laptop can take minutes
X8_SETS = ("x8-pages", "x8-pages-r2", "x8-pages-r3")  # sealed truth with tables
OCR_PROMPT = "Text Recognition:"  # GLM-OCR's prompt for text (X43 B2)


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
    cased = commands.add_parser(
        "plan-cases", help="plan a single-question key and write its bundle (v4)"
    )
    cased.add_argument("--catalogue", type=Path, required=True)
    cased.add_argument("--brief", type=Path, required=True)
    cased.add_argument(
        "--agents", type=Path, required=True, help="the writer's AGENTS.md"
    )
    cased.add_argument("--out", type=Path, required=True)
    cased.add_argument("--seed", type=int, required=True)
    cased.add_argument("--per-part", type=int, default=16)
    cased.add_argument("--limit", type=int, default=8000, help="characters per source")
    cased.add_argument(
        "--design", type=Path, help="prefix, counts, reuse and styles (default: v4's)"
    )
    cased.add_argument(
        "--earlier",
        type=Path,
        nargs="*",
        default=[],
        help="sets whose sources wait their turn and whose quotes are taken",
    )
    cased.add_argument(
        "--rendered",
        type=Path,
        help="a web-render folder: pages shown as a browser shows them (v6)",
    )
    checked = commands.add_parser(
        "check-cases", help="check a single-question key against its bundle"
    )
    checked.add_argument("keys", nargs="+", type=Path, help="the key's JSON files")
    checked.add_argument(
        "--plan", type=Path, required=True, help="the bundle's plan.json"
    )
    checked.add_argument("--catalogue", type=Path, required=True)
    checked.add_argument(
        "--out-set",
        type=Path,
        help="when clean, write key.json and questions.json here",
    )
    checked.add_argument("--seed", type=int, help="shuffles the blind questions")
    checked.add_argument(
        "--withdraw",
        action="append",
        default=[],
        metavar="CASE",
        help="leave a case out of the plan and the key (its reason goes in the report)",
    )
    redrawn = commands.add_parser(
        "replace-cases", help="new sources for cases the writer flagged (v4)"
    )
    redrawn.add_argument("bundle", type=Path, help="the bundle folder")
    redrawn.add_argument("cases", nargs="+", help="flagged case ids")
    redrawn.add_argument("--catalogue", type=Path, required=True)
    redrawn.add_argument("--seed", type=int, required=True)
    redrawn.add_argument(
        "--part", type=int, required=True, help="the new part's number"
    )
    redrawn.add_argument(
        "--limit", type=int, default=8000, help="characters per source"
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
    reached = commands.add_parser(
        "reach", help="did the passages each answer's model was given hold the evidence"
    )
    replayed_searches = commands.add_parser(
        "replay", help="the first request and the searches, scored by reach (E5)"
    )
    replayed_searches.add_argument("name")
    replayed_searches.add_argument("--version", type=int, required=True)
    replayed_searches.add_argument(
        "--parts", type=Path, help="an earlier replay, whose search questions are kept"
    )
    replayed_searches.add_argument("--out", type=Path, required=True)
    replayed_searches.add_argument(
        "--scoped", action="store_true", help="search again inside named products (B4)"
    )
    again = commands.add_parser(
        "embed-again", help="an index version copied with another embedder (E5)"
    )
    again.add_argument("--version", type=int, required=True, help="index version")
    again.add_argument("--url", required=True, help="the other embedding server")
    again.add_argument("--model", required=True, help="its model, as recorded")
    claimed = commands.add_parser(
        "claim-items", help="the labelled claims of graded sittings, as gate items (E5)"
    )
    claimed.add_argument(
        "--set",
        dest="sittings",
        nargs=3,
        action="append",
        required=True,
        metavar=("NAME", "SITTING", "REPLAY"),
        help="a set, its graded sitting folder and a replay file (for the parts)",
    )
    claimed.add_argument("--out", type=Path, required=True)
    reranked = commands.add_parser(
        "claim-rerank", help="each claim scored against its parts by a reranker (E5)"
    )
    reranked.add_argument("items", type=Path)
    reranked.add_argument("--url", default="", help="another reranking server")
    reranked.add_argument("--out", type=Path, required=True)
    supported = commands.add_parser(
        "claim-support", help="each claim scored against its quotes on the CPU (E5)"
    )
    supported.add_argument("items", type=Path)
    supported.add_argument("--model", type=Path, required=True, help="model folder")
    supported.add_argument("--out", type=Path, required=True)
    read = commands.add_parser(
        "claim-reader", help="each claim's parts asked of its text by a reader (E5)"
    )
    read.add_argument("items", type=Path)
    read.add_argument("--model", type=Path, required=True, help="model folder")
    read.add_argument("--text", choices=("quotes", "claim"), required=True)
    read.add_argument("--out", type=Path, required=True)
    abstained = commands.add_parser(
        "claim-answerable",
        help="each claim's parts judged answerable from its sources (E8 specialist)",
    )
    abstained.add_argument("items", type=Path)
    abstained.add_argument("--url", required=True, help="the answerability server")
    where = abstained.add_mutually_exclusive_group(required=True)
    where.add_argument("--sources", type=Path, help="a slot-extract file's sources")
    where.add_argument(
        "--passages", action="store_true", help="each near-miss case's whole passage"
    )
    abstained.add_argument("--out", type=Path, required=True)
    slotted = commands.add_parser(
        "slot-extract", help="the slots claims' parts ask and their sources state (E7)"
    )
    slotted.add_argument("--items", type=Path, required=True, help="claim items")
    slotted.add_argument(
        "--set",
        dest="sittings",
        nargs=2,
        action="append",
        default=[],
        metavar=("NAME", "SITTING"),
        help="a set and its graded sitting folder (claims' sources, unless in items)",
    )
    slotted.add_argument("--out", type=Path, required=True)
    compared = commands.add_parser(
        "slot-compare", help="each claim scored by its slots (E7 comparators a-c)"
    )
    compared.add_argument("slots", type=Path, help="the slot-extract file")
    compared.add_argument("--items", type=Path, required=True, help="claim items")
    compared.add_argument(
        "--by", choices=("product", "reranker", "judge"), required=True
    )
    compared.add_argument("--version", type=int, help="index version (product names)")
    compared.add_argument("--out", type=Path, required=True)
    smoked = commands.add_parser(
        "smoke", help="does a candidate generator do both requests at all (E8 G0)"
    )
    smoked.add_argument("--url", required=True, help="the candidate's server")
    smoked.add_argument("--set", dest="name", required=True, help="questions' set")
    smoked.add_argument("--items", type=Path, required=True, help="near-miss items")
    smoked.add_argument("--version", type=int, required=True, help="index version")
    smoked.add_argument("--out", type=Path, required=True)
    near_written = commands.add_parser(
        "nearmiss-write", help="near-miss questions written from passages (E7 S3)"
    )
    near_written.add_argument("--version", type=int, required=True)
    near_written.add_argument("--count", type=int, required=True, help="passages")
    near_written.add_argument("--seed", type=int, required=True)
    near_written.add_argument("--out", type=Path, required=True)
    near_checked = commands.add_parser(
        "nearmiss-check", help="keep the questions a second model agrees with (E7 S3)"
    )
    near_checked.add_argument("items", type=Path)
    near_checked.add_argument("--version", type=int, required=True)
    near_checked.add_argument("--url", required=True, help="the second model's server")
    near_checked.add_argument("--out", type=Path, required=True)
    web_audited = commands.add_parser(
        "web-audit", help="cached pages against what the extractor keeps (X42 W0)"
    )
    web_audited.add_argument("--out", type=Path, required=True)
    web_sampled = commands.add_parser(
        "web-sample", help="the pages whose ground truth is judged (X42 W1)"
    )
    web_sampled.add_argument("--seed", type=int, required=True)
    web_sampled.add_argument("--out", type=Path, required=True)
    web_sampled.add_argument(
        "--held-out", type=Path, help="draw W2b's pages from outside this sample"
    )
    web_rendered = commands.add_parser(
        "web-render", help="screenshots and visible text of sampled pages (X42 W1)"
    )
    web_rendered.add_argument("sample", type=Path, help="a web-sample file")
    web_rendered.add_argument("--out", type=Path, required=True, help="a folder")
    web_truthed = commands.add_parser(
        "web-truth", help="ground truth from judged page outlines (X42 W1)"
    )
    web_truthed.add_argument("render", type=Path, help="a web-render folder")
    web_truthed.add_argument(
        "--set", type=Path, required=True, help="the set's folder, holding outlines/"
    )
    web_scored = commands.add_parser(
        "web-score", help="an extractor arm against the web-pages truth (X42 W2)"
    )
    web_scored.add_argument("arm", choices=webpages.ARMS)
    web_scored.add_argument("--set", default="web-pages", help="a registered truth")
    web_scored.add_argument("--out", type=Path, required=True)
    web_facted = commands.add_parser(
        "web-facts", help="one question per web-pages truth block (X42 W3)"
    )
    web_facted.add_argument("--out-set", type=Path, required=True, help="a folder")
    web_retrieved = commands.add_parser(
        "web-retrieval", help="score an index version's search on web-facts (X42 W3)"
    )
    web_retrieved.add_argument("--version", type=int, required=True)
    web_retrieved.add_argument("--out", type=Path, required=True)
    web_compared = commands.add_parser(
        "web-compare", help="web-facts arms against the baseline (X42 W3)"
    )
    web_compared.add_argument("baseline", type=Path, help="a web-retrieval file")
    web_compared.add_argument("arms", type=Path, nargs="+")
    web_compared.add_argument("--set", default="web-facts", help="or image-facts")
    image_drawn = commands.add_parser(
        "image-candidates", help="images drawn for the OCR truth (X43 B2)"
    )
    image_drawn.add_argument("--seed", type=int, required=True)
    image_drawn.add_argument("--catalogue", type=Path, required=True)
    image_drawn.add_argument("--count", type=int, default=60, help="per source")
    image_drawn.add_argument("--out", type=Path, required=True, help="a folder")
    docx_scored = commands.add_parser(
        "docx-score", help="a Word reading against the docx-pages truth (X43 A3a)"
    )
    docx_scored.add_argument(
        "arm", choices=("docling-word", "rendered-pdf", "rendered-pdf-lines")
    )
    docx_scored.add_argument("--vlm", default="", help="a vision server for tables")
    docx_scored.add_argument("--out", type=Path, required=True, help="a folder")
    layout_checked = commands.add_parser(
        "layout-check", help="X8 readings rescored with side-by-side lines (X43 A3a)"
    )
    layout_checked.add_argument("name", help="an X8 truth set")
    layout_checked.add_argument("run", type=Path, help="a saved parsed.json")
    layout_checked.add_argument("--arm", required=True)
    image_read = commands.add_parser(
        "image-ocr", help="each image-text image read by a vision server (X43 B2)"
    )
    image_read.add_argument("--url", required=True, help="the vision model's server")
    image_read.add_argument("--out", type=Path, required=True)
    image_scored = commands.add_parser(
        "image-ocr-score", help="OCR readings against the image-text truth (X43 B2)"
    )
    image_scored.add_argument("readings", type=Path, help="an image-ocr file")
    picture_retrieved = commands.add_parser(
        "image-retrieval", help="score a version's search on image-facts (X43 B3)"
    )
    picture_retrieved.add_argument("--version", type=int, required=True)
    picture_retrieved.add_argument("--out", type=Path, required=True)
    web_linked = commands.add_parser(
        "web-links", help="the link of every passage of a version checked (X42 W4)"
    )
    web_linked.add_argument("--version", type=int, required=True)
    web_linked.add_argument(
        "--rendered", type=Path, nargs="*", default=[], help="web-render folders"
    )
    web_linked.add_argument("--out", type=Path, required=True)
    near_answered = commands.add_parser(
        "nearmiss-answer", help="claims shown per question from its passage (E7 S4)"
    )
    near_answered.add_argument("items", type=Path)
    near_answered.add_argument("--version", type=int, required=True)
    near_answered.add_argument("--url", required=True, help="the generator's server")
    near_answered.add_argument("--out", type=Path, required=True)
    joined_slots = commands.add_parser(
        "slot-gate", help="the product check before a phrase score (E7 comparator d)"
    )
    joined_slots.add_argument("product", type=Path)
    joined_slots.add_argument("phrase", type=Path)
    joined_slots.add_argument("--out", type=Path, required=True)
    termed = commands.add_parser(
        "claim-terms",
        help="each claim scored by its quotes' share of a part's words (E5)",
    )
    termed.add_argument("items", type=Path)
    termed.add_argument("--version", type=int, required=True, help="index version")
    termed.add_argument("--out", type=Path, required=True)
    joined = commands.add_parser(
        "claim-combine", help="the mean percentile rank of several detectors (E5)"
    )
    joined.add_argument("scores", type=Path, nargs="+", help="scores files")
    joined.add_argument("--out", type=Path, required=True)
    gated = commands.add_parser(
        "claim-score", help="a detector's scores against the labelled claims (E5)"
    )
    gated.add_argument("items", type=Path)
    gated.add_argument("scores", type=Path, help='{"item id": score}, higher = correct')
    gated.add_argument("--seed", type=int, required=True)
    drafted = commands.add_parser(
        "drafts", help="draft again the answers whose checks removed a claim (E5)"
    )
    drafted.add_argument("runs", type=Path, nargs="+", help="answers files from ask")
    drafted.add_argument("--out", type=Path, required=True)
    rescored = commands.add_parser(
        "verify-score", help="labelled removed drafts checked again as the code stands"
    )
    rescored.add_argument("items", type=Path, help="a drafts file")
    rescored.add_argument("labels", type=Path, help='{"id/n": {"label": ...}}')
    dropped = commands.add_parser(
        "removed", help="every claim a run's checks removed, for reading (C3)"
    )
    dropped.add_argument("run", type=Path, help="an answers file from `ask` (v1 API)")
    dropped.add_argument("--out", type=Path, required=True)
    dropped.add_argument("--reason", default="", help="only claims removed for this")
    reached.add_argument("name")
    reached.add_argument("run", type=Path, help="an answers file from `ask` (v1 API)")
    reached.add_argument("--out", type=Path, help="a JSON file with every part's row")
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
    hidden = commands.add_parser("blind", help="write runs' different answers, blind")
    hidden.add_argument("name")
    hidden.add_argument(
        "runs",
        type=Path,
        nargs="+",
        help="answers files, baselines first, candidate last",
    )
    hidden.add_argument("--seed", type=int, required=True)
    hidden.add_argument(
        "--all",
        action="store_true",
        help="every question, not only differing ones (R0)",
    )
    hidden.add_argument("--out", type=Path, required=True)
    shown = commands.add_parser("unblind", help="compare runs from blind verdicts")
    shown.add_argument("name")
    shown.add_argument("runs", type=Path, nargs="+", help="the files given to blind")
    shown.add_argument("--dir", type=Path, required=True)
    shown.add_argument("--json", action="store_true")
    replayed = commands.add_parser(
        "replay-requests", help="rebuild answer requests from audit records (X39)"
    )
    replayed.add_argument("runs", type=Path, nargs="+", help="answers files from ask")
    replayed.add_argument("--out", type=Path, required=True)
    degraded = commands.add_parser(
        "degradation-requests", help="answer requests of 8-64 passages (X39 M3)"
    )
    degraded.add_argument("sets", nargs="+", help="keyed sets")
    degraded.add_argument("--version", type=int, required=True)
    degraded.add_argument("--warm-up", type=Path, required=True, help="replay file")
    degraded.add_argument("--out", type=Path, required=True)
    turned = commands.add_parser(
        "conversation-requests", help="understanding requests per turn (X39 M4)"
    )
    turned.add_argument("name", help="a conversation set, e.g. conv-v1")
    turned.add_argument("--window", type=int, required=True, help="turns of history")
    turned.add_argument("--warm-up", type=Path, required=True, help="replay file")
    turned.add_argument("--interleave", action="store_true", help="answer requests too")
    turned.add_argument("--out", type=Path, required=True)
    passed = commands.add_parser("generator-pass", help="send requests, time them")
    passed.add_argument("url", help="the scratch server, e.g. http://127.0.0.1:8083")
    passed.add_argument("requests", type=Path)
    passed.add_argument("--out", type=Path, required=True)
    passed.add_argument("--pid", type=int, help="the server's process id, for memory")
    passed.add_argument("--cache-prompt", action="store_true", help="reuse prompts")
    passed.add_argument("--concurrency", type=int, default=1, help="requests at once")
    passed.add_argument("--server", default="", help="its command line, recorded")
    compared = commands.add_parser("generator-compare", help="a step against kept")
    compared.add_argument("kept", type=Path)
    compared.add_argument("step", type=Path)
    compared.add_argument("--noise", type=Path, nargs=2, help="base passes A and B")
    diagnosed = commands.add_parser(
        "generator-diagnose", help="where differing replies part, and how close"
    )
    diagnosed.add_argument("url", help="a server running the kept configuration")
    diagnosed.add_argument("requests", type=Path)
    diagnosed.add_argument("kept", type=Path)
    diagnosed.add_argument("step", type=Path)
    benched = commands.add_parser(
        "relevance-items", help="a relevance benchmark from answer runs"
    )
    benched.add_argument("runs", type=Path, nargs="+", help="answers files from `ask`")
    benched.add_argument("--out", type=Path, required=True)
    checked = commands.add_parser("relevance-check", help="one candidate on it")
    checked.add_argument("items", type=Path)
    checked.add_argument("--candidate", choices=relevance.CANDIDATES, required=True)
    checked.add_argument("--out", type=Path, required=True)
    scored_relevance = commands.add_parser("relevance-score", help="against labels")
    scored_relevance.add_argument("labels", type=Path)
    scored_relevance.add_argument("results", type=Path)
    reliable = commands.add_parser("reliability", help="risk, coverage, refusals (R0)")
    reliable.add_argument("name")
    reliable.add_argument(
        "runs", type=Path, nargs="+", help="answers files, one per arm"
    )
    reliable.add_argument(
        "--dir", type=Path, required=True, help="a graded blind sitting"
    )
    reliable.add_argument(
        "--reach", type=Path, nargs="*", default=[], help="reach-<run>.json rows files"
    )
    reliable.add_argument(
        "--baseline", default="", help="the arm coverage is compared to"
    )
    reliable.add_argument(
        "--verdicts",
        default="verdicts.json",
        help="the sitting's verdicts file, e.g. the settled majority's",
    )
    reliable.add_argument("--out", type=Path)
    bundled = commands.add_parser(
        "grading-bundle", help="blind items for second graders"
    )
    bundled.add_argument("name")
    bundled.add_argument(
        "--dir", type=Path, required=True, help="a graded blind sitting"
    )
    bundled.add_argument("--out", type=Path, required=True, help="a folder to write")
    bundled.add_argument("--share", type=float, default=0.3)
    bundled.add_argument("--seed", type=int, required=True)
    modelled = commands.add_parser(
        "grade-with-model", help="a local model grades items"
    )
    modelled.add_argument("items", type=Path)
    modelled.add_argument(
        "url", help="the grading model's server, e.g. http://127.0.0.1:8083"
    )
    modelled.add_argument("--out", type=Path, required=True)
    agreed = commands.add_parser("agreement", help="Cohen's kappa between two graders")
    agreed.add_argument("first", type=Path)
    agreed.add_argument("second", type=Path)
    settled = commands.add_parser(
        "settle", help="the majority of three graders' verdicts, for the readout"
    )
    settled.add_argument("dir", type=Path, help="a graded blind sitting")
    settled.add_argument("others", type=Path, nargs="+", help="second graders' files")
    settled.add_argument(
        "--settled", type=Path, help="{item: grade} for items with no majority"
    )
    settled.add_argument("--out", type=Path, required=True)
    exposed = commands.add_parser(
        "exposure", help="the first request on an exposure set (C2's safety bar)"
    )
    exposed.add_argument("name", help="e.g. exposure-v1")
    exposed.add_argument("--out", type=Path, required=True)
    verified = commands.add_parser(
        "generator-outcomes", help="verified outcomes of two passes' replies (X41)"
    )
    verified.add_argument("requests", type=Path)
    verified.add_argument("kept", type=Path)
    verified.add_argument("step", type=Path)
    curved = commands.add_parser("degradation-curve", help="score M3's pass")
    curved.add_argument("requests", type=Path)
    curved.add_argument("run", type=Path)
    curved.add_argument("--out", type=Path, required=True)
    sized = commands.add_parser("support-sizes", help="longest inputs (X40)")
    sized.add_argument("role", choices=["embed", "rerank"])
    sized.add_argument("url", help="a server of that role, e.g. http://127.0.0.1:8081")
    sized.add_argument("--version", type=int, required=True)
    loaded = commands.add_parser("support-workload", help="X40's workload on a server")
    loaded.add_argument("role", choices=["embed", "rerank"])
    loaded.add_argument("url", help="the server under test")
    loaded.add_argument("--version", type=int, required=True)
    loaded.add_argument("--pid", type=int, required=True, help="the server's process")
    loaded.add_argument("--log", type=Path, required=True, help="the server's log")
    loaded.add_argument("--out", type=Path, required=True)
    matched = commands.add_parser("support-compare", help="an arm against arm 0")
    matched.add_argument("base", type=Path)
    matched.add_argument("arm", type=Path)
    reused = commands.add_parser("prompt-reuse", help="summarise M4's pass")
    reused.add_argument("requests", type=Path)
    reused.add_argument("run", type=Path)
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


def earlier_use(
    folders: list[Path], entries: list[dict[str, Any]]
) -> tuple[frozenset[str], dict[str, list[str]]]:
    """From earlier sets (each with `plan.json` and `key.json`): the catalogue entries
    their cases used, and the quotes their keys took from each entry."""
    by_url = {entry["url"]: entry["id"] for entry in entries}
    served: set[str] = set()
    taken: dict[str, list[str]] = {}
    for folder in folders:
        shown = grades.read_json(folder / "plan.json")["sources"].values()
        served.update(source["entry"] for source in shown)
        for case in grades.read_json(folder / "key.json")["cases"]:
            for part in case["parts"]:
                for item in part["evidence"]:
                    taken.setdefault(by_url[item["url"]], []).append(item["quote"])
    return frozenset(served), taken


def run_plan_cases(args: argparse.Namespace) -> int:
    entries = grades.read_json(args.catalogue)
    design = grades.read_json(args.design) if args.design else cases.V4
    unindexed = set(design.get("unindexed", cases.UNINDEXED))
    texts = {
        e["id"]: cases.source_text(e, args.rendered)
        for e in entries
        if e["format"] not in unindexed
    }
    served, taken = earlier_use(args.earlier, entries)
    planned = cases.plan(entries, texts, args.seed, design, served)
    notes = {
        "brief.md": args.brief.read_text(encoding="utf-8"),
        "AGENTS.md": args.agents.read_text(encoding="utf-8"),
    }
    parts = cases.bundle(
        planned, entries, texts, notes, args.out, args.per_part, args.limit, args.seed,
        design["reuse"], taken, args.rendered,
    )  # fmt: skip
    by_id = {entry["id"]: entry for entry in entries}
    formats = Counter(by_id[c["sources"][0]]["format"] for c in planned if c["sources"])
    for label, count in sorted(formats.items()):
        print(f"{count:5}  {label}")
    sources = sum(len(c["sources"]) for c in planned)
    print(f"{len(planned)} cases, {sources} sources, {len(parts)} parts in {args.out}")
    return 0


def run_replace_cases(args: argparse.Namespace) -> int:
    plan_file = args.bundle / "plan.json"
    seen = grades.read_json(plan_file)
    unknown = set(args.cases) - {case["id"] for case in seen["plan"]}
    if unknown:
        raise ValueError(f"not planned: {', '.join(sorted(unknown))}")
    part = args.bundle / f"part-{args.part}.md"
    if part.exists():
        raise ValueError(f"{part} exists already")
    entries = grades.read_json(args.catalogue)
    texts = {
        e["id"]: cases.source_text(e)
        for e in entries
        if e["format"] not in cases.UNINDEXED
    }
    replaced, text = cases.rebundle(
        seen, set(args.cases), entries, texts, args.limit, args.seed
    )
    # The first plan stays beside the new one: the writer saw both.
    shutil.copyfile(plan_file, args.bundle / f"plan-before-part-{args.part}.json")
    write_json(plan_file, replaced)
    part.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(args.cases)} cases given new sources in {part}")
    return 0


def run_check_cases(args: argparse.Namespace) -> int:
    seen = grades.read_json(args.plan)
    written = [c for path in args.keys for c in grades.read_json(path)["cases"]]
    if args.withdraw:
        # A case no draw of sources could support leaves the set before it is sealed.
        seen["plan"] = [c for c in seen["plan"] if c["id"] not in args.withdraw]
        written = [c for c in written if c.get("id") not in args.withdraw]
        print("withdrawn:", ", ".join(args.withdraw))
    pdfs = {sid for sid, s in seen["sources"].items() if s["entry"].startswith("file:")}
    pictures = frozenset(
        sid for sid, s in seen["sources"].items() if s["entry"].startswith("picture:")
    )
    corpus_files = sorted((args.plan.parent / "corpus").glob("*.txt"))
    corpus = [keys.normalise(path.read_text(encoding="utf-8")) for path in corpus_files]
    found = cases.key_problems({"cases": written}, seen, pdfs, corpus, pictures)
    for problem in found:
        print("PROBLEM", problem)
    wordings = sum(len(c.get("wordings", [])) for c in written)
    print(f"{len(written)} cases, {wordings} wordings, {len(found)} problems")
    if found or not args.out_set:
        return 1 if found else 0
    key_file, blind_file = args.out_set / "key.json", args.out_set / "questions.json"
    if key_file.exists() or blind_file.exists():
        # A key written into a set is sealed by its hash, so it is never replaced.
        print(f"key not written: {args.out_set} already holds a key")
        return 1
    if args.seed is None:
        raise ValueError("--seed is needed to shuffle the blind questions")
    entries = {e["id"]: e for e in grades.read_json(args.catalogue)}
    key = cases.sealed({"cases": written}, seen, entries)
    rows = keys.blind_questions(key, args.seed, f"v{key['version']}q")
    write_json(key_file, key)
    write_json(blind_file, {"questions": rows})
    print(f"key and {len(rows)} blind questions written to {args.out_set}")
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
        written = tables.recognise(image, args.vlm, args.prompt)
        scored = parsing.transcription(page["words"], written)
        answers[page["number"]] = {"answer": written, **scored}
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


def run_removed(args: argparse.Namespace) -> int:
    rows = []
    with assistant.connect() as conn:
        for record in grades.read_json(args.run):
            if "answer_id" not in record:
                continue
            kept = [claim["text"] for claim in record["view"]["claims"]]
            for item in store.removed_claims(conn, record["answer_id"]):
                if args.reason and item["reason"] != args.reason:
                    continue
                rows.append({"id": record["id"], "question": record["question"],
                             "removed": item["text"], "reason": item["reason"],
                             "kept": kept})  # fmt: skip
    write_json(args.out, rows)
    reasons = Counter(row["reason"] for row in rows)
    print(f"{len(rows)} removed claims in {args.out}: {dict(reasons)}")
    return 0


def run_reach(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    given: dict[str, list[Passage]] = {}
    versions = set()
    with assistant.connect() as conn:
        for record in grades.read_json(args.run):
            if "answer_id" in record:
                version, passages = store.given_passages(conn, record["answer_id"])
                versions.add(version)
                given[record["id"]] = passages
        if len(versions) != 1:
            raise ValueError(
                f"the run must use one index version, not {sorted(versions)}"
            )
        texts = store.searchable_texts(conn, versions.pop())
    rows = reach.score(key, questions, given, texts)
    found = reach.summary(rows)
    if args.out:
        write_json(args.out, {"summary": found, "rows": rows})
    print(reach.text(found))
    return 0


def run_replay(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    parts = grades.read_json(args.parts)["parts"] if args.parts else None
    with assistant.connect() as conn:
        written, given = replay.replay(
            key,
            questions,
            lambda question: answer.understand(question, llm.chat),
            assistant.retriever(conn, args.version),
            parts,
            assistant.scoped_retriever(conn, args.version) if args.scoped else None,
        )
        texts = store.searchable_texts(conn, args.version)
    rows = reach.score(key, questions, given, texts)
    found = reach.summary(rows)
    passages = {qid: [p.id for p in shown] for qid, shown in given.items()}
    saved = {"summary": found, "rows": rows, "parts": written, "passages": passages}
    write_json(args.out, saved)
    print(reach.text(found))
    return 0


def run_embed_again(args: argparse.Namespace) -> int:
    with assistant.connect() as conn:
        version = versions.embedded_again(
            conn, args.version, lambda texts: llm.embed(texts, args.url), args.model
        )
    print(f"version {args.version} embedded again by {args.model}: version {version}")
    return 0


def run_claim_items(args: argparse.Namespace) -> int:
    found: list[claims.Item] = []
    for name, sitting, replayed in args.sittings:
        folder = sets.require(name, args.root, args.registry)
        found += claims.items(
            name,
            grades.read_json(folder / "key.json"),
            grades.read_json(folder / "questions.json")["questions"],
            grades.read_json(Path(sitting) / "pairs.json"),
            grades.read_json(Path(sitting) / "claims.json"),
            grades.read_json(Path(replayed))["parts"],
        )
    write_json(args.out, found)
    counts = Counter(item["label"] for item in found)
    print(f"{len(found)} claims in {args.out}: {dict(sorted(counts.items()))}")
    return 0


def run_claim_rerank(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    scores = claims.by_reranker(found, lambda q, docs: llm.rerank(q, docs, args.url))
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_support(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    scores = detectors.by_support(found, detectors.support_model(args.model))
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_reader(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    reader = detectors.reader_model(args.model)
    scores = detectors.by_reader(found, reader, args.text)
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_answerable(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    if args.sources:
        texts = abstainer.quoted(grades.read_json(args.sources)["sources"])
    else:
        with assistant.connect() as conn:
            texts = abstainer.whole(found, case_passages(conn, found))
    scores = abstainer.by_parts(found, texts, graders.post_to(args.url))
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_slot_extract(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    blinded = {
        name: grades.read_json(Path(sitting) / "pairs.json")
        for name, sitting in args.sittings
    }
    if blinded:
        sources = slotbench.claim_sources(found, blinded)
    else:
        sources = {item["id"]: [tuple(s) for s in item["sources"]] for item in found}
    extracted = slotbench.extract(found, sources, llm.chat)
    write_json(args.out, {"sources": sources, **extracted})
    asked, stated = len(extracted["asked"]), len(extracted["stated"])
    print(f"{asked} parts and {stated} sources read in {args.out}")
    return 0


def run_slot_compare(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    read = grades.read_json(args.slots)
    sources = {key: [tuple(s) for s in value] for key, value in read["sources"].items()}
    if args.by == "product":
        with assistant.connect() as conn:
            named = scope.naming(store.product_names(conn, args.version))
        scores = slotbench.by_product(found, sources, named)
    else:
        pair_score = (
            slotbench.reranker_pairs(llm.rerank)
            if args.by == "reranker"
            else slotbench.judge_pairs(llm.CLIENT.post)
        )
        scores = slotbench.by_pairs(found, sources, read, pair_score)
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def case_passages(conn: store.Connection, found: list[Any]) -> dict[str, Passage]:
    """The passage behind each near-miss case ("p<passage id>")."""
    ids = sorted({int(item["case"][1:]) for item in found})
    return {f"p{p.id}": p for p in store.load_passages(conn, ids)}


def run_smoke(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    questions = grades.read_json(folder / "questions.json")["questions"]
    found = grades.read_json(args.items)[: candidates.COUNT]
    with assistant.connect() as conn:
        passages = case_passages(conn, found)
    result = candidates.smoke(
        [q["question"] for q in questions], found, passages, graders.post_to(args.url)
    )
    write_json(args.out, result)
    print(json.dumps(result))
    return 0


def run_nearmiss_write(args: argparse.Namespace) -> int:
    with assistant.connect() as conn:
        chosen = nearmiss.sample(
            store.searchable_passages(conn, args.version), args.count, args.seed
        )
    found = [item for passage in chosen for item in nearmiss.written(passage, llm.chat)]
    write_json(args.out, found)
    print(f"{len(found)} questions from {len(chosen)} passages in {args.out}")
    return 0


def run_nearmiss_check(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    with assistant.connect() as conn:
        passages = case_passages(conn, found)
    kept = nearmiss.checked(found, passages, graders.post_to(args.url))
    write_json(args.out, kept)
    print(f"{len(kept)} of {len(found)} questions kept in {args.out}")
    return 0


def cached_html() -> dict[str, str]:
    """Every cached site page's HTML by its cache name."""
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(config.PAGE_CACHE.glob("*.html"))
    }


def run_web_audit(args: argparse.Namespace) -> int:
    found = webpages.audit(cached_html())
    write_json(args.out, found)
    print(json.dumps(found["total"]))
    return 0


def run_web_sample(args: argparse.Namespace) -> int:
    if args.held_out:
        drawn = {row["slug"] for row in grades.read_json(args.held_out)}
        chosen = webpages.held_out(cached_html(), drawn, args.seed)
    else:
        chosen = webpages.sample(cached_html(), args.seed)
    rows = [{"slug": slug, "type": webpages.page_type(slug)} for slug in chosen]
    write_json(args.out, rows)
    print(f"{len(rows)} pages in {args.out}: {dict(Counter(r['type'] for r in rows))}")
    return 0


def run_web_render(args: argparse.Namespace) -> int:
    slugs = [row["slug"] for row in grades.read_json(args.sample)]
    with webpages.chromium() as browser:
        counts = webpages.render(slugs, cached_html(), args.out, browser)
    print(f"{len(counts)} pages rendered to {args.out}; visible words {counts}")
    return 0


def run_web_truth(args: argparse.Namespace) -> int:
    """Each outline over its page's rendered text becomes the page's truth; the
    texts are copied into the set beside the outlines that number their lines."""
    texts = {}
    truth = {}
    problems = []
    for path in sorted((args.set / "outlines").glob("*.json")):
        text = (args.render / f"{path.stem}.txt").read_text(encoding="utf-8")
        lines = webpages.visible_lines(text)
        outline = grades.read_json(path)
        found = webpages.outline_problems(outline, len(lines))
        problems += [f"{path.stem}: {problem}" for problem in found]
        if not found:
            texts[path.stem] = text
            truth[path.stem] = webpages.build_truth(outline, lines)
    if problems:
        print("\n".join(problems))
        return 1
    (args.set / "visible").mkdir(exist_ok=True)
    for slug, text in texts.items():
        (args.set / "visible" / f"{slug}.txt").write_text(text, encoding="utf-8")
    write_json(args.set / "truth.json", truth)
    blocks = sum(len(page["blocks"]) for page in truth.values())
    print(f"{len(truth)} pages, {blocks} blocks in {args.set / 'truth.json'}")
    return 0


def run_web_score(args: argparse.Namespace) -> int:
    """One arm's readings of the sampled pages, scored against the registered truth;
    the readings are kept with the scores for diagnosis."""
    truth = grades.read_json(
        sets.require(args.set, args.root, args.registry) / "truth.json"
    )
    pages = cached_html()
    converter = webpages.docling_converter() if args.arm == "docling" else None
    readings = {}
    for slug in truth:
        if args.arm == "current":
            readings[slug] = webpages.current_reading(pages[slug])
        elif args.arm == "fixed":
            readings[slug] = webpages.fixed_reading(pages[slug])
        elif args.arm == "docling":
            readings[slug] = webpages.docling_reading(pages[slug], converter)
        else:
            readings[slug] = webpages.trafilatura_reading(pages[slug])
    found = webpages.scores(truth, readings)
    write_json(args.out, found | {"readings": readings})
    print(json.dumps({name: round(rate, 4) for name, rate in found["rates"].items()}))
    return 0


def run_web_facts(args: argparse.Namespace) -> int:
    """W3's set from the registered truth; each fact's holders are the pages whose
    text (`limespec.webpage`) holds its evidence."""
    truth = grades.read_json(
        sets.require("web-pages", args.root, args.registry) / "truth.json"
    )
    texts = {}
    for slug, raw in cached_html().items():
        _, found = webpage.read_page(raw)
        texts[ingest.page_url(slug)] = "\n".join(element["text"] for element in found)
    items = webpages.fact_items(truth, texts)
    args.out_set.mkdir(parents=True, exist_ok=True)
    write_json(args.out_set / "questions.json", {"questions": items})
    shared = sum(len(item["holders"]) > 1 for item in items)
    print(f"{len(items)} facts ({shared} held by more than one page) in {args.out_set}")
    return 0


def run_web_retrieval(args: argparse.Namespace) -> int:
    folder = sets.require("web-facts", args.root, args.registry)
    items = grades.read_json(folder / "questions.json")["questions"]
    results = []
    anywhere: dict[str, list[Passage]] = {}
    with assistant.connect() as conn:
        for item in items:
            for url in item["holders"]:
                if url not in anywhere:
                    anywhere[url] = store.document_passages(conn, args.version, url)
            ranked = store.search(
                conn, args.version, item["question"], llm.embed, llm.rerank
            )
            held = [p for url in item["holders"] for p in anywhere[url]]
            results.append(webpages.fact_result(item, ranked, held))
        passages = store.passage_count(conn, args.version)
    found = lookups.summary(results)["web-facts"]
    record = {"version": args.version, "passages": passages, "summary": found}
    write_json(args.out, {**record, "results": results})
    print(
        f"web-facts: {found['count']:.0f} facts, Success@{lookups.TOP} "
        f"{found['success']:.3f}, MRR {found['mrr']:.3f}, ceiling "
        f"{found['ceiling']:.3f}; {passages} passages in version {args.version}"
    )
    return 0


def run_web_links(args: argparse.Namespace) -> int:
    """Each passage linked as a claim would be, by its first line and by its first
    two lines (a range), every link checked; pages rendered by `web-render` are
    checked against their rendering too."""
    rendered = {}
    for folder in args.rendered:
        for path in sorted(folder.glob("*.txt")):
            rendered[ingest.page_url(path.stem)] = path.read_text(encoding="utf-8")
    with assistant.connect() as conn:
        found = store.searchable_passages(conn, args.version)
    problems: list[dict[str, str]] = []
    checked = 0
    for passage in found:
        lines = [line for line in passage.text.split("\n") if line.strip()]
        for quote in (lines[0], "\n".join(lines[:2])):
            link = verify.source_link(passage, quote)
            checked += 1
            for problem in webpages.link_problems(link, rendered.get(passage.url)):
                problems.append({"problem": problem, "link": link})
    write_json(args.out, {"links": checked, "problems": problems})
    kinds = Counter(problem["problem"] for problem in problems)
    print(f"{checked} links from {len(found)} passages; problems: {dict(kinds)}")
    return 0


def run_image_candidates(args: argparse.Namespace) -> int:
    """The first `count` site images and PDF figures in drawing order, each written
    as the PNG the index would keep (and OCR would read), with candidates.json."""
    formats = {
        entry["url"]: entry["format"] for entry in grades.read_json(args.catalogue)
    }
    readings = [
        grades.read_json(path)
        for path in sorted(config.READINGS.glob("*.json"))
        if path.name != "report.json"
    ]
    site = imagesets.site_candidates(acquire.read_manifest(), args.seed)
    figures = imagesets.figure_candidates(readings, formats, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    kept = []
    for candidate in site[: args.count] + figures[: args.count]:
        stored = acquire.store_path(candidate["sha256"])
        if "page" in candidate:
            png = images.crop(stored, candidate["page"], tuple(candidate["box"]))
        else:
            png = images.normalised(stored.read_bytes())
        name = candidate["id"].replace("/", "__") + ".png"
        (args.out / name).write_bytes(png)
        kept.append(candidate | {"png": name})
    write_json(args.out / "candidates.json", kept)
    print(f"{len(kept)} candidates in {args.out}")
    return 0


def run_docx_score(args: argparse.Namespace) -> int:
    """Each registered declaration read by one arm and scored; the readings are kept
    beside the scores for diagnosis."""
    folder = sets.require("docx-pages", args.root, args.registry)
    truth = grades.read_json(folder / "truth.json")["pages"]
    readings = {}
    for sha256 in dict.fromkeys(page["sha256"] for page in truth):
        stored = acquire.store_path(sha256)
        if args.arm == "docling-word":
            readings[sha256] = office.read_docx(stored)
        else:
            rendered = office.render_pdf(stored, args.out / "rendered")
            readings[sha256] = pdf.read_pdf(rendered, vlm=args.vlm)
            if args.arm == "rendered-pdf-lines":
                readings[sha256] = layout.side_by_side(readings[sha256])
    found = docxpages.scores(truth, readings)
    saved = {sha: [asdict(e) for e in elements] for sha, elements in readings.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / f"{args.arm}.json", found | {"readings": saved})
    print(json.dumps({name: round(rate, 4) for name, rate in found["rates"].items()}))
    print(json.dumps(found["passed"]))
    return 0


def run_layout_check(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    truth = grades.read_json(folder / "truth.json")["pages"]
    found = docxpages.layout_check(truth, grades.read_json(args.run), args.arm)
    for name in ("before", "after"):
        print(name, json.dumps({k: round(v, 4) for k, v in found[name].items()}))
    print("falls:", found["falls"] or "none")
    return 1 if found["falls"] else 0


def run_image_ocr(args: argparse.Namespace) -> int:
    """Each registered image read with GLM-OCR's text prompt; a rerun keeps the
    readings already saved."""
    from PIL import Image

    folder = sets.require("image-text", args.root, args.registry)
    truth = grades.read_json(folder / "truth.json")
    readings = grades.read_json(args.out) if args.out.exists() else {}
    for image in truth["images"]:
        if image["id"] in readings:
            continue
        with Image.open(folder / "images" / image["png"]) as picture:
            readings[image["id"]] = tables.recognise(
                picture.convert("RGB"), args.url, OCR_PROMPT
            )
        write_json(args.out, readings)
    print(f"{len(readings)} images read into {args.out}")
    return 0


def run_image_ocr_score(args: argparse.Namespace) -> int:
    folder = sets.require("image-text", args.root, args.registry)
    truth = grades.read_json(folder / "truth.json")
    found = imagesets.ocr_score(truth["images"], grades.read_json(args.readings))
    for name, rates in found["rates"].items():
        print(
            f"{name}: recall {rates['recall']:.3f}, precision {rates['precision']:.3f}"
        )
    return 0


def run_image_retrieval(args: argparse.Namespace) -> int:
    folder = sets.require("image-facts", args.root, args.registry)
    items = grades.read_json(folder / "questions.json")["questions"]
    results = []
    with assistant.connect() as conn:
        for item in items:
            ranked = store.search(
                conn, args.version, item["question"], llm.embed, llm.rerank
            )
            results.append(imagesets.picture_result(item, ranked))
    found = lookups.summary(results)["image-facts"]
    write_json(
        args.out, {"version": args.version, "summary": found, "results": results}
    )
    print(f"image-facts: Success@{lookups.TOP} {found['success']:.3f}, MRR "
          f"{found['mrr']:.3f}; version {args.version}")  # fmt: skip
    return 0


def run_web_compare(args: argparse.Namespace) -> int:
    baseline = grades.read_json(args.baseline)
    for path in args.arms:
        arm = grades.read_json(path)
        change = lookups.compare(arm["results"], baseline["results"], args.set)
        print(
            f"{path.name}: Success@{lookups.TOP} {arm['summary']['success']:.3f} vs "
            f"{baseline['summary']['success']:.3f}, difference "
            f"{change['difference']:+.3f} [{change['low']:+.3f}, {change['high']:+.3f}]"
        )
    return 0


def run_nearmiss_answer(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    with assistant.connect() as conn:
        passages = case_passages(conn, found)
    shown = nearmiss.shown_claims(found, passages, graders.post_to(args.url))
    write_json(args.out, shown)
    print(f"{len(shown)} questions answered in {args.out}")
    return 0


def run_slot_gate(args: argparse.Namespace) -> int:
    scores = slotbench.gated(
        grades.read_json(args.product), grades.read_json(args.phrase)
    )
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_terms(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    with assistant.connect() as conn:
        weights = detectors.rarity(store.searchable_texts(conn, args.version))
    scores = detectors.by_terms(found, weights)
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_combine(args: argparse.Namespace) -> int:
    scores = detectors.combined([grades.read_json(path) for path in args.scores])
    write_json(args.out, scores)
    print(f"{len(scores)} claims scored in {args.out}")
    return 0


def run_claim_score(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    scores = grades.read_json(args.scores)
    missing = [item["id"] for item in found if item["id"] not in scores]
    if missing:
        raise ValueError(f"{len(missing)} items have no score, e.g. {missing[0]}")
    print(json.dumps(claims.score(found, scores, args.seed), indent=1))
    return 0


def run_drafts(args: argparse.Namespace) -> int:
    records = [record for path in args.runs for record in grades.read_json(path)]
    found = []
    seen = set()
    with assistant.connect() as conn:
        for record in records:
            if "answer_id" not in record:
                continue
            if not store.removed_claims(conn, record["answer_id"]):
                continue
            _, passages = store.given_passages(conn, record["answer_id"])
            # The view's question is the one the model was asked (stripped).
            question = record["view"]["question"]
            request = (question, tuple(passage.id for passage in passages))
            if request in seen:
                continue
            seen.add(request)
            item = drafts.drafted(question, passages, llm.chat)
            found.append({"id": f"a{record['answer_id']}", "question": question,
                          "passages": list(request[1]), **item})  # fmt: skip
    write_json(args.out, found)
    count = len(drafts.removed(found))
    print(f"{len(found)} answers drafted again, {count} drafts removed; in {args.out}")
    return 0


def run_verify_score(args: argparse.Namespace) -> int:
    items = grades.read_json(args.items)
    rows = grades.read_json(args.labels)
    labels = {name: row["label"] for name, row in rows.items()}
    unknown = set(labels.values()) - set(drafts.LABELS)
    if set(labels) != set(drafts.removed(items)) or unknown:
        raise ValueError("label every removed draft, and nothing else, wrong or right")
    wanted = sorted({passage for item in items for passage in item["passages"]})
    with assistant.connect() as conn:
        loaded = store.load_passages(conn, wanted)
    passages = {passage.id: passage for passage in loaded}
    print(json.dumps(drafts.rescore(items, labels, passages), indent=1))
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


def load_runs(paths: list[Path]) -> dict[str, pairs.Records]:
    """Answers files by run name (the file name without "answers-"), in the order
    given: at least two, the candidate last."""
    runs = {}
    for path in paths:
        records = grades.read_json(path)
        runs[path.stem.removeprefix("answers-")] = {r["id"]: r for r in records}
    if len(runs) < 2 or len(runs) != len(paths):
        raise ValueError("give at least two runs, each with a different file name")
    return runs


def run_blind(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    questions = grades.read_json(folder / "questions.json")["questions"]
    runs = load_runs(args.runs)
    ids = [row["id"] for row in questions]
    if not args.all:
        ids = pairs.differing(runs, ids)
    blinded, order = pairs.blind(ids, runs, args.seed)
    ask.write_records(args.out / "pairs.json", blinded)
    (args.out / "order.json").write_text(json.dumps(order, indent=1), encoding="utf-8")
    written = "every question" if args.all else "answers that differ"
    print(f"{len(ids)} of {len(questions)} questions ({written}); pairs in {args.out}")
    return 0


def run_unblind(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    runs = load_runs(args.runs)
    order = grades.read_json(args.dir / "order.json")
    if not (args.dir / "verdicts.json").exists():
        raise ValueError(f"grade the pairs first: no verdicts.json in {args.dir}")
    verdicts = grades.read_json(args.dir / "verdicts.json")
    if set(verdicts) != set(order):
        raise ValueError("verdicts.json must grade every pair in pairs.json")
    graded = pairs.unblind(verdicts, order)
    *baselines, candidate = runs
    results = [
        pairs.compare(
            key, questions, {name: runs[name], candidate: runs[candidate]}, graded
        )
        for name in baselines
    ]
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        print("\n".join(pairs.markdown(result) for result in results), end="")
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


def run_replay_requests(args: argparse.Namespace) -> int:
    records = [record for path in args.runs for record in grades.read_json(path)]
    by_id = {r["answer_id"]: r for r in records if "answer_id" in r}
    requests = []
    with assistant.connect() as conn:
        for answer_id in generator.replay_ids(records):
            _, passages = store.given_passages(conn, answer_id)
            # The view's question is the one the model was asked (stripped).
            question = by_id[answer_id]["view"]["question"]
            requests.append(
                generator.answer_request(f"a{answer_id}", question, passages)
            )
    write_json(args.out, {"warm_up": requests[:1], "requests": requests[1:]})
    print(f"1 warm-up and {len(requests) - 1} requests in {args.out}")
    return 0


def run_degradation_requests(args: argparse.Namespace) -> int:
    requests: list[generator.Request] = []
    skipped = []
    with assistant.connect() as conn:
        version = store.searchable_passages(conn, args.version)
        for name in args.sets:
            folder = sets.require(name, args.root, args.registry)
            key = grades.read_json(folder / "key.json")
            questions = grades.read_json(folder / "questions.json")["questions"]
            for case, question in generator.degradation_cases(key, questions):
                ranking = generator.deep_ranking(
                    conn, args.version, question["question"], llm.embed, llm.rerank
                )
                quotes = generator.case_quotes(case)
                evidence = generator.evidence_passages(quotes, ranking, version)
                label = f"{name}/{case['id']}"
                if evidence is None:
                    skipped.append(f"{label}: a quote is in no passage")
                    continue
                if len(evidence) > generator.MAX_EVIDENCE:
                    skipped.append(f"{label}: {len(evidence)} evidence passages")
                    continue
                others = generator.distractors(ranking, evidence, quotes)
                requests.extend(
                    generator.degradation_requests(
                        name, case, question, evidence, others
                    )
                )
    warm_up = grades.read_json(args.warm_up)["warm_up"]
    write_json(args.out, {"warm_up": warm_up, "requests": requests, "skipped": skipped})
    print(f"{len(requests)} requests in {args.out}; {len(skipped)} cases left out")
    for reason in skipped:
        print(f"  {reason}")
    return 0


def run_conversation_requests(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    replay = grades.read_json(args.warm_up)
    answers = replay["requests"] if args.interleave else []
    requests = generator.conversation_requests(key, args.window, answers)
    write_json(args.out, {"warm_up": replay["warm_up"], "requests": requests})
    print(f"{len(requests)} requests in {args.out}")
    return 0


def run_generator_pass(args: argparse.Namespace) -> int:
    requests = grades.read_json(args.requests)
    url = args.url.rstrip("/") + "/v1/chat/completions"
    result = generator.run_pass(
        url,
        requests,
        args.cache_prompt,
        lambda: generator.memory_sample(args.pid),
        concurrency=args.concurrency,
    )
    result["server"] = args.server
    write_json(args.out, result)
    speeds = generator.speeds(result["replies"])
    print(
        f"{len(result['replies'])} replies in {args.out}: prompt "
        f"{speeds['prompt_per_second']:.0f} tokens/s, generation "
        f"{speeds['generation_per_second']:.1f} tokens/s, "
        f"{speeds['mean_seconds']:.1f} s per request, "
        f"{result['wall_seconds']:.0f} s in all; memory {result['memory']}"
    )
    return 0


def run_generator_compare(args: argparse.Namespace) -> int:
    kept = grades.read_json(args.kept)
    step = grades.read_json(args.step)
    noise = 0.0
    if args.noise:
        first, second = (grades.read_json(path)["replies"] for path in args.noise)
        noise = generator.noise(first, second)
    found = generator.compare(kept["replies"], step["replies"], noise)
    found["noise"] = noise
    found["speeds"] = {
        "kept": generator.speeds(kept["replies"]),
        "step": generator.speeds(step["replies"]),
    }
    found["memory"] = step["memory"]
    print(json.dumps(found, indent=1))
    return 0


def run_generator_diagnose(args: argparse.Namespace) -> int:
    requests = {r["id"]: r for r in grades.read_json(args.requests)["requests"]}
    kept = {r["id"]: r for r in grades.read_json(args.kept)["replies"]}
    step = grades.read_json(args.step)["replies"]
    found = {}
    for reply in step:
        if reply["content"] != kept[reply["id"]]["content"]:
            found[reply["id"]] = generator.diagnose(
                args.url.rstrip("/") + "/v1/chat/completions",
                requests[reply["id"]],
                kept[reply["id"]]["content"],
                reply["content"],
            )
    print(json.dumps(found, indent=1))
    defects = [i for i, row in found.items() if not row["numeric"]]
    print(f"{len(found)} replies differ; not numeric: {defects or 'none'}")
    return 0


def dev_questions(args: argparse.Namespace) -> list[str]:
    """The dev sets' questions in file order: frozen90, held-out v2, held-out v3."""
    found = []
    for name in ("frozen90", "heldout-v2", "heldout-v3"):
        folder = sets.require(name, args.root, args.registry)
        found += [
            q["question"]
            for q in grades.read_json(folder / "questions.json")["questions"]
        ]
    return found


def tokens(url: str, text: str) -> int:
    """How many tokens the server at `url` reads for `text`."""
    response = httpx.post(
        url.rstrip("/") + "/tokenize", json={"content": text}, headers=llm.auth(),
        timeout=ANSWER_TIMEOUT_SECONDS,
    )  # fmt: skip
    response.raise_for_status()
    return len(response.json()["tokens"])


def support_inputs(
    args: argparse.Namespace,
) -> tuple[list[str], list[str], list[tuple[str, list[str]]], tuple[str, list[str]]]:
    """X40's inputs: every searchable passage's embedding text, 50 queries, and 100
    rerank calls of 20 keyword candidates plus one of 100 (version `args.version`)."""
    questions = dev_questions(args)
    with assistant.connect() as conn:
        passages = store.searchable_passages(conn, args.version)

        def candidates(question: str, limit: int) -> list[str]:
            ids = store.keyword_ranking(conn, args.version, question, limit)
            return [described(p.title, p.context, p.text)
                    for p in store.load_passages(conn, ids)]  # fmt: skip

        calls = [(q, candidates(q, 20)) for q in questions[:100]]
        deep = (questions[0], candidates(questions[0], 100))
    texts = [described(p.title, p.context, p.text) for p in passages]
    queries = [config.QUERY_INSTRUCTION + q for q in questions[:50]]
    return texts, queries, calls, deep


def run_support_sizes(args: argparse.Namespace) -> int:
    texts, queries, calls, deep = support_inputs(args)
    if args.role == "embed":
        longest = max(tokens(args.url, text) for text in [*texts, *queries])
    else:
        documents = {d for _, docs in [*calls, deep] for d in docs}
        # A rerank input is the question and one candidate, plus a few special tokens.
        longest = (max(tokens(args.url, q) for q, _ in calls)
                   + max(tokens(args.url, d) for d in documents) + 4)  # fmt: skip
    print(f"{args.role}: longest input {longest} tokens; size "
          f"{support.smallest_power(longest)}")  # fmt: skip
    return 0


def run_support_workload(args: argparse.Namespace) -> int:
    texts, queries, calls, deep = support_inputs(args)
    if args.role == "embed":
        found = support.embed_workload(
            texts, queries, lambda batch: llm.embed(batch, args.url)
        )
    else:
        found = support.rerank_workload(
            calls, deep, lambda q, docs: llm.rerank(q, docs, args.url)
        )
    found["gpu_mib"] = support.gpu_process_mib(args.pid)
    found["kv_full"] = support.kv_full_lines(args.log.read_text(encoding="utf-8"))
    write_json(args.out, found)
    summary = {k: round(v, 3) for k, v in found.items() if isinstance(v, (int, float))}
    print(json.dumps(summary))
    return 0


def run_support_compare(args: argparse.Namespace) -> int:
    base = grades.read_json(args.base)
    arm = grades.read_json(args.arm)
    if "vectors" in base:
        outputs: dict[str, float] = {
            "lowest_cosine": support.same_vectors(base["vectors"], arm["vectors"])
        }
    else:
        outputs = support.same_scores(base["scores"], arm["scores"])
    measures = {k: v for k, v in arm.items() if isinstance(v, (int, float))}
    print(json.dumps({**outputs, **measures}, indent=1))
    return 0


def run_relevance_items(args: argparse.Namespace) -> int:
    records = [record for run in args.runs for record in grades.read_json(run)]
    found = relevance.items(records, lambda q: answer.understand(q, llm.chat)[1])
    write_json(args.out, found)
    claims = sum(len(item["claims"]) for item in found)
    print(f"{len(found)} answers, {claims} claims in {args.out}")
    return 0


def run_relevance_check(args: argparse.Namespace) -> int:
    results = relevance.check(args.candidate, grades.read_json(args.items))
    write_json(args.out, results)
    print(f"{len(results)} items checked by {args.candidate} in {args.out}")
    return 0


def run_relevance_score(args: argparse.Namespace) -> int:
    result = relevance.score(
        grades.read_json(args.labels), grades.read_json(args.results)
    )
    print(json.dumps(result, indent=1))
    return 0


def run_reliability(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    runs = load_runs(args.runs)
    order = grades.read_json(args.dir / "order.json")
    graded = pairs.unblind(grades.read_json(args.dir / args.verdicts), order)
    rows = reliability.case_rows(key, questions, graded, runs)
    reached = {
        path.stem.removeprefix("reach-"): reliability.reached_parts(
            grades.read_json(path)["rows"]
        )
        for path in args.reach
    }
    result: dict[str, Any] = {
        "arms": reliability.by_arm(rows),
        "attribution": reliability.attribution(rows, reached),
    }
    if args.baseline:
        result["coverage_difference"] = {
            arm: reliability.coverage_difference(rows, arm, args.baseline)
            for arm in runs
            if arm != args.baseline
        }
    if (args.dir / "claims.json").exists():
        labels = reliability.claims_by_arm(
            grades.read_json(args.dir / "claims.json"), order
        )
        result["claims"] = {
            arm: reliability.claim_precision(labels[arm]) for arm in labels
        }
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, indent=1))
    return 0


def run_grading_bundle(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    key = grades.read_json(folder / "key.json")
    questions = grades.read_json(folder / "questions.json")["questions"]
    found = graders.items(key, questions, grades.read_json(args.dir / "pairs.json"))
    primary = graders.flat(grades.read_json(args.dir / "verdicts.json"))
    chosen = graders.sample(found, primary, args.share, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    shown = [{k: v for k, v in item.items() if k != "type"} for item in chosen]
    write_json(args.out / "items.json", shown)
    shutil.copyfile(graders.GUIDE, args.out / "grading-guide.md")
    print(f"{len(chosen)} of {len(found)} items in {args.out}")
    return 0


def run_grade_with_model(args: argparse.Namespace) -> int:
    found = grades.read_json(args.items)
    verdicts = graders.grade(
        found, graders.GUIDE.read_text(encoding="utf-8"), graders.post_to(args.url)
    )
    write_json(args.out, verdicts)
    print(f"{len(verdicts)} items graded in {args.out}")
    return 0


def run_agreement(args: argparse.Namespace) -> int:
    result = graders.agreement(
        graders.flat(grades.read_json(args.first)),
        graders.flat(grades.read_json(args.second)),
    )
    print(json.dumps(result, indent=1))
    return 0


def run_settle(args: argparse.Namespace) -> int:
    settled = grades.read_json(args.settled) if args.settled else {}
    final, unsettled = graders.settle(
        grades.read_json(args.dir / "verdicts.json"),
        [graders.flat(grades.read_json(path)) for path in args.others],
        settled,
    )
    if unsettled:
        raise ValueError(f"settle these items with a reason: {', '.join(unsettled)}")
    write_json(args.out, final)
    changed = graders.agreement(
        graders.flat(grades.read_json(args.dir / "verdicts.json")), graders.flat(final)
    )
    print(f"{changed['items'] - changed['agreed']} verdicts changed; in {args.out}")
    return 0


def run_exposure(args: argparse.Namespace) -> int:
    folder = sets.require(args.name, args.root, args.registry)
    questions = grades.read_json(folder / "questions.json")
    result = guardrails.exposures(
        questions, lambda q: answer.describes_exposure(q, llm.chat)
    )
    write_json(args.out, result)
    print(
        f"exposures caught {result['caught']}/{result['exposures']}; false alarms "
        f"{len(result['false_alarms'])}/{result['ordinary']}"
    )
    return 0


def run_generator_outcomes(args: argparse.Namespace) -> int:
    requests = {r["id"]: r for r in grades.read_json(args.requests)["requests"]}
    ids = {i for r in requests.values() for i in r["passage_ids"]}
    with assistant.connect() as conn:
        passages = {p.id: p for p in store.load_passages(conn, sorted(ids))}
    found = []
    for path in (args.kept, args.step):
        outcomes = {}
        for reply in grades.read_json(path)["replies"]:
            request = requests[reply["id"]]
            outcomes[reply["id"]] = generator.evidence_used(request, reply, passages)
        found.append(outcomes)
    kept, step = found
    changed = {
        i: {"kept": kept[i], "step": step[i]} for i in kept if kept[i] != step[i]
    }
    statuses = [Counter(o["status"] for o in each.values()) for each in found]
    summary = {"kept": statuses[0], "step": statuses[1], "outcome_changed": changed}
    print(json.dumps(summary, indent=1))
    return 0


def run_degradation_curve(args: argparse.Namespace) -> int:
    requests = {r["id"]: r for r in grades.read_json(args.requests)["requests"]}
    replies = grades.read_json(args.run)["replies"]
    ids = {i for r in requests.values() for i in r["passage_ids"]}
    with assistant.connect() as conn:
        passages = {p.id: p for p in store.load_passages(conn, sorted(ids))}
    rows = []
    for reply in replies:
        request = requests[reply["id"]]
        outcome = generator.evidence_used(request, reply, passages)
        rows.append({"id": reply["id"], **request["data"], **outcome})
    found = generator.curve(rows)
    write_json(args.out, {"curve": found, "rows": rows})
    for size, entry in found["sizes"].items():
        against = entry["against_smallest"]
        print(
            f"{size:>3} passages: used {entry['used']:.3f} "
            f"[{entry['low']:.3f}, {entry['high']:.3f}]; against the smallest "
            f"{against['difference']:+.3f} [{against['low']:+.3f}, "
            f"{against['high']:+.3f}]"
        )
    print(f"passage budget: {found['budget']}")
    return 0


def run_prompt_reuse(args: argparse.Namespace) -> int:
    requests = grades.read_json(args.requests)["requests"]
    replies = grades.read_json(args.run)["replies"]
    print(json.dumps(generator.reuse(requests, replies), indent=1))
    return 0


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
        if args.command == "plan-cases":
            return run_plan_cases(args)
        if args.command == "check-cases":
            return run_check_cases(args)
        if args.command == "replace-cases":
            return run_replace_cases(args)
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
        if args.command == "reach":
            return run_reach(args)
        if args.command == "replay":
            return run_replay(args)
        if args.command == "drafts":
            return run_drafts(args)
        if args.command == "embed-again":
            return run_embed_again(args)
        if args.command == "claim-items":
            return run_claim_items(args)
        if args.command == "claim-rerank":
            return run_claim_rerank(args)
        if args.command == "claim-support":
            return run_claim_support(args)
        if args.command == "claim-reader":
            return run_claim_reader(args)
        if args.command == "claim-answerable":
            return run_claim_answerable(args)
        if args.command == "slot-extract":
            return run_slot_extract(args)
        if args.command == "slot-compare":
            return run_slot_compare(args)
        if args.command == "smoke":
            return run_smoke(args)
        if args.command == "nearmiss-write":
            return run_nearmiss_write(args)
        if args.command == "nearmiss-check":
            return run_nearmiss_check(args)
        if args.command == "web-audit":
            return run_web_audit(args)
        if args.command == "web-sample":
            return run_web_sample(args)
        if args.command == "web-render":
            return run_web_render(args)
        if args.command == "web-truth":
            return run_web_truth(args)
        if args.command == "web-score":
            return run_web_score(args)
        if args.command == "web-facts":
            return run_web_facts(args)
        if args.command == "web-retrieval":
            return run_web_retrieval(args)
        if args.command == "docx-score":
            return run_docx_score(args)
        if args.command == "layout-check":
            return run_layout_check(args)
        if args.command == "image-ocr":
            return run_image_ocr(args)
        if args.command == "image-ocr-score":
            return run_image_ocr_score(args)
        if args.command == "image-candidates":
            return run_image_candidates(args)
        if args.command == "image-retrieval":
            return run_image_retrieval(args)
        if args.command == "web-links":
            return run_web_links(args)
        if args.command == "web-compare":
            return run_web_compare(args)
        if args.command == "nearmiss-answer":
            return run_nearmiss_answer(args)
        if args.command == "slot-gate":
            return run_slot_gate(args)
        if args.command == "claim-terms":
            return run_claim_terms(args)
        if args.command == "claim-combine":
            return run_claim_combine(args)
        if args.command == "claim-score":
            return run_claim_score(args)
        if args.command == "verify-score":
            return run_verify_score(args)
        if args.command == "page-candidates":
            return run_page_candidates(args)
        if args.command == "blind":
            return run_blind(args)
        if args.command == "unblind":
            return run_unblind(args)
        if args.command == "replay-requests":
            return run_replay_requests(args)
        if args.command == "degradation-requests":
            return run_degradation_requests(args)
        if args.command == "conversation-requests":
            return run_conversation_requests(args)
        if args.command == "generator-pass":
            return run_generator_pass(args)
        if args.command == "generator-compare":
            return run_generator_compare(args)
        if args.command == "generator-diagnose":
            return run_generator_diagnose(args)
        if args.command == "removed":
            return run_removed(args)
        if args.command == "relevance-items":
            return run_relevance_items(args)
        if args.command == "relevance-check":
            return run_relevance_check(args)
        if args.command == "relevance-score":
            return run_relevance_score(args)
        if args.command == "reliability":
            return run_reliability(args)
        if args.command == "grading-bundle":
            return run_grading_bundle(args)
        if args.command == "grade-with-model":
            return run_grade_with_model(args)
        if args.command == "agreement":
            return run_agreement(args)
        if args.command == "settle":
            return run_settle(args)
        if args.command == "exposure":
            return run_exposure(args)
        if args.command == "generator-outcomes":
            return run_generator_outcomes(args)
        if args.command == "degradation-curve":
            return run_degradation_curve(args)
        if args.command == "prompt-reuse":
            return run_prompt_reuse(args)
        if args.command == "support-sizes":
            return run_support_sizes(args)
        if args.command == "support-workload":
            return run_support_workload(args)
        if args.command == "support-compare":
            return run_support_compare(args)
        return run_ask(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

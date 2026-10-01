"""Experiment X9's questions and scores: does search find the passage holding the
evidence (evaluation/reports/X9-table-passages.md)?

Two sets. Table lookups come from the X8 truth grids, written from page images for
X8 and so not from any X9 arm: one question per data cell, "In the {title}, what is
the {column header} for {row label}?", its evidence the row label and the value on
that page. The conv-v1 set is every quote a key writer took from a PDF, asked by its
turn's standalone question. A passage is relevant when it belongs to the evidence's
document (and page, for a lookup) and `verify.find_quote` finds every evidence text
in it: the rule that keeps a claim at answer time.
"""

from collections.abc import Sequence
from typing import Any

from evaluation import metrics
from evaluation.parsing import header_and_rows
from limespec.ingest import file_title
from limespec.models import Passage, as_read
from limespec.verify import find_quote

DASHES = {"-", "–", "—"}  # a cell that only marks "none"
TOP = 8  # the reranked passages the answer model reads
BASELINE = "table"  # X9's baseline arm: whole tables, as the readings keep them
TIE = 0.02  # table-lookup Success@8 differences within this are ties
Item = dict[str, Any]  # id, set, question, sha256, page (None: any), evidence, cluster


def usable(text: str) -> bool:
    """Whether a cell can name or answer a question: not empty, not a dash."""
    return bool(text) and text not in DASHES


def table_questions(
    name: str, pages: Sequence[dict[str, Any]], titles: dict[str, str]
) -> list[Item]:
    """One question per usable data cell of a truth set's tables, each asked once."""
    found: list[Item] = []
    asked: set[str] = set()
    for page in pages:
        sha256 = page["entry"].split(":", 1)[1]
        title = titles.get(page["url"]) or file_title(page["url"])
        for number, table in enumerate(page["tables"], 1):
            header, rows = header_and_rows(table)
            cluster = f"{name}/{page['number']}/{number}"
            for index, row in enumerate(rows):
                label = row[0].strip() if row else ""
                for column in range(1, len(row)):
                    head = header[column].strip() if column < len(header) else ""
                    value = row[column].strip()
                    if not (usable(label) and usable(head) and usable(value)):
                        continue
                    question = f"In the {title}, what is the {head} for {label}?"
                    if question in asked:
                        continue
                    asked.add(question)
                    found.append({
                        "id": f"{cluster}/{index}/{column}",
                        "set": "x9-tables",
                        "question": question,
                        "sha256": sha256,
                        "page": page["page"],
                        "evidence": [label, value],
                        "cluster": cluster,
                    })  # fmt: skip
    return found


def quote_items(
    key: dict[str, Any], plan: dict[str, Any], pdfs: set[str]
) -> list[Item]:
    """Every conv-v1 quote from a PDF with a reading (`pdfs`: their SHA-256s)."""
    sources = {
        conversation["id"]: conversation["sources"] for conversation in plan["plan"]
    }
    found: list[Item] = []
    for conversation in key["conversations"]:
        for turn in conversation["turns"]:
            for part in turn.get("parts", []):
                for number, evidence in enumerate(part.get("evidence", []), 1):
                    index = int(evidence["source"].rsplit("-s", 1)[1]) - 1
                    kind, _, sha256 = sources[conversation["id"]][index].partition(":")
                    if kind != "file" or sha256 not in pdfs:
                        continue
                    found.append({
                        "id": f"{turn['id']}/{part['id']}/{number}",
                        "set": "conv-v1",
                        "question": turn["standalone_question"],
                        "sha256": sha256,
                        "page": None,
                        "evidence": [evidence["quote"]],
                        "cluster": turn["id"],
                    })  # fmt: skip
    return found


def relevant(passage: Passage, item: Item, url: str) -> bool:
    """Whether the passage, as the model reads it (`models.as_read`), holds the
    item's evidence."""
    if passage.url != url:
        return False
    if item["page"] is not None and passage.page != item["page"]:
        return False
    return all(find_quote(text, as_read(passage)) for text in item["evidence"])


def score_item(
    item: Item, ranked: Sequence[Passage], anywhere: Sequence[Passage], url: str
) -> dict[str, Any]:
    """One item's result: its first relevant rank in the top passages (`ranked`),
    and whether any passage of its document holds the evidence at all (the ceiling)."""
    rank = None
    for position, passage in enumerate(ranked[:TOP], 1):
        if relevant(passage, item, url):
            rank = position
            break
    return {
        "id": item["id"],
        "set": item["set"],
        "cluster": item["cluster"],
        "success": 1.0 if rank else 0.0,
        "reciprocal": 1 / rank if rank else 0.0,
        "ceiling": 1.0 if any(relevant(p, item, url) for p in anywhere) else 0.0,
    }


def summary(results: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Success@8, MRR@8 and the ceiling for each set."""
    found = {}
    for name in sorted({result["set"] for result in results}):
        mine = [result for result in results if result["set"] == name]
        found[name] = {
            "count": len(mine),
            "success": metrics.mean([result["success"] for result in mine]),
            "mrr": metrics.mean([result["reciprocal"] for result in mine]),
            "ceiling": metrics.mean([result["ceiling"] for result in mine]),
        }
    return found


def compare(
    arm: Sequence[dict[str, Any]], baseline: Sequence[dict[str, Any]], name: str
) -> dict[str, float]:
    """An arm's Success@8 minus the baseline's on one set, with its interval
    (clusters resampled)."""
    by_id = {result["id"]: result for result in baseline if result["set"] == name}
    mine = [result for result in arm if result["set"] == name]
    return metrics.paired_cluster_bootstrap(
        [result["success"] for result in mine],
        [by_id[result["id"]]["success"] for result in mine],
        [result["cluster"] for result in mine],
    )


def select(arms: dict[str, dict[str, Any]]) -> str:
    """The pre-registered rule. An arm is eligible if its conv-v1 Success@8 is at
    most one quote below the baseline's. The baseline stays unless an eligible arm
    beats its table-lookup Success@8 by more than TIE; among those, the highest
    wins, and within TIE of it, the arm with fewer passages."""

    def lookups(name: str) -> float:
        return float(arms[name]["summary"]["x9-tables"]["success"])

    quotes = arms[BASELINE]["summary"]["conv-v1"]
    floor = quotes["success"] - 1 / quotes["count"]
    better = [
        name
        for name, arm in arms.items()
        if arm["summary"]["conv-v1"]["success"] >= floor - 1e-9
        and lookups(name) > lookups(BASELINE) + TIE
    ]
    if not better:
        return BASELINE
    best = max(lookups(name) for name in better)
    close = [name for name in better if best - lookups(name) <= TIE]
    return min(close, key=lambda name: (arms[name]["passages"], name))

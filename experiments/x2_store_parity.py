"""X2: does the Postgres store rank passages as well as the SQLite store?

    uv run --env-file .env python -m experiments.x2_store_parity

The store is the only difference between the arms. A temporary Postgres index
version is copied from the SQLite index (the same pages, passages and vectors),
each question is embedded once, and that one vector is ranked by both stores.
Keyword ranking differs by design (SQLite FTS5 BM25, Postgres ts_rank); vector
ranking should match. The live Postgres version, re-embedded by `limespec ingest
--postgres`, is reported beside them for information. Rankings are scored against
the frozen 90 and held-out v2 answer keys; the gate is that no Postgres measure is
worse than SQLite beyond the paired bootstrap interval. The copy is deleted at the
end. Needs the dev Postgres and the embedding server.
"""

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import psycopg

from evaluation import retrieval, sets
from limespec import config, llm, store
from limespec.retrieve import Embed, from_blob, fuse, keyword_ranking, vector_ranking

SETS = ("frozen90", "heldout-v2")
DEPTH = retrieval.DEPTH  # 20 candidates per method, as in the saved runs
METHODS = ("keyword", "vector", "fused")
OUT = Path("data/runs/x2")
# Postgres arm -> {Postgres passage id: SQLite passage id}, and its version id
Arms = dict[str, tuple[int, dict[int, int]]]


def copy_sqlite_index(sqlite_conn: sqlite3.Connection, pg: store.Connection) -> int:
    """A Postgres index version (not live) holding exactly the SQLite index."""
    pages = sqlite_conn.execute(
        "SELECT url, title, fetched_at, sha256 FROM pages"
    ).fetchall()
    rows = sqlite_conn.execute(
        "SELECT passages.url, pages.title, passages.heading, passages.text, "
        "passages.embedding FROM passages JOIN pages USING (url) ORDER BY passages.id"
    ).fetchall()
    manifest = dict(sqlite_conn.execute("SELECT key, value FROM meta").fetchall())
    passages = []
    vectors = []
    for url, title, heading, text, blob in rows:
        passages.append((url, title, heading, text))
        vectors.append(list(from_blob(blob)))
    return store.write_version(pg, pages, passages, vectors, manifest)


def sqlite_ids(
    pg: store.Connection, version_id: int, sqlite_conn: sqlite3.Connection
) -> dict[int, int]:
    """Postgres passage id -> SQLite passage id, matched by page URL and text."""
    by_content = {}
    for passage_id, url, text in sqlite_conn.execute(
        "SELECT id, url, text FROM passages"
    ):
        by_content[(url, text)] = passage_id
    mapping = {}
    for passage_id, url, text in pg.execute(
        "SELECT passages.id, documents.url, passages.text FROM passages "
        "JOIN documents ON documents.id = passages.document_id "
        "WHERE index_version_id = %s",
        (version_id,),
    ).fetchall():
        mapping[passage_id] = by_content[(url, text)]
    return mapping


def rankings(
    question: str,
    query_vector: list[float],
    sqlite_conn: sqlite3.Connection,
    pg: store.Connection,
    arms: Arms,
) -> dict[str, list[int]]:
    """Every arm's keyword, vector and fused ranking, all as SQLite passage ids."""
    keyword = keyword_ranking(sqlite_conn, question, DEPTH)
    vector = vector_ranking(sqlite_conn, query_vector, DEPTH)
    found = {
        "sqlite-keyword": keyword,
        "sqlite-vector": vector,
        "sqlite-fused": fuse([keyword, vector])[:DEPTH],
    }
    for arm, (version_id, to_sqlite) in arms.items():
        keyword = [
            to_sqlite[i] for i in store.keyword_ranking(pg, version_id, question, DEPTH)
        ]
        vector = [
            to_sqlite[i]
            for i in store.vector_ranking(pg, version_id, query_vector, DEPTH)
        ]
        found[f"{arm}-keyword"] = keyword
        found[f"{arm}-vector"] = vector
        found[f"{arm}-fused"] = fuse([keyword, vector])[:DEPTH]
    return found


def run_set(
    folder: Path,
    embed: Embed,
    sqlite_conn: sqlite3.Connection,
    pg: store.Connection,
    arms: Arms,
) -> list[retrieval.Part]:
    """Every judged part of a set with every arm's rankings."""
    relevant = retrieval.read_qrels(folder / "retrieval" / "qrels.txt")
    questions = {}
    for row in json.loads((folder / "questions.json").read_text(encoding="utf-8"))[
        "questions"
    ]:
        questions[row["id"]] = row["question"]
    found_by_question: dict[str, dict[str, list[int]]] = {}
    parts = []
    for part_id, ids in relevant.items():
        question_id = retrieval.question_of(part_id)
        if question_id not in found_by_question:
            text = questions[question_id]
            query_vector = embed([config.QUERY_INSTRUCTION + text])[0]
            found_by_question[question_id] = rankings(
                text, query_vector, sqlite_conn, pg, arms
            )
        parts.append(
            retrieval.Part(
                part_id, question_id, frozenset(ids), found_by_question[question_id]
            )
        )
    return parts


def compare(parts: list[retrieval.Part], arm: str, method: str) -> dict[str, Any]:
    """One Postgres arm against SQLite for one method, on the same parts."""
    baseline, candidate = f"sqlite-{method}", f"{arm}-{method}"
    pair = [
        retrieval.Part(
            p.part_id,
            p.question_id,
            p.relevant,
            {baseline: p.rankings[baseline], candidate: p.rankings[candidate]},
        )
        for p in parts
    ]
    return retrieval.score(pair, baseline=baseline)


def gate_failures(result: dict[str, Any]) -> list[str]:
    """Comparisons whose whole 95% interval lies below zero (significantly worse)."""
    failures = []
    for row in result["comparisons"]:
        if row["high"] < 0:
            failures.append(f"{row['pair']} {row['metric']} {row['difference']:+.3f}")
    return failures


def report(name: str, parts: list[retrieval.Part], arms: Arms) -> list[str]:
    """Print one set's comparison table; return its gate failures (parity arm only)."""
    questions = len({p.question_id for p in parts})
    print(f"\n## {name}: {questions} questions, {len(parts)} parts\n")
    print(
        "| Arm vs SQLite | Method | Success@8 | nDCG@10 | MRR@10 | Every part @8 "
        "| Worse beyond the interval |"
    )
    print("|---|---|---|---|---|---|---|")
    failures = []
    for arm in arms:
        for method in METHODS:
            result = compare(parts, arm, method)
            cells = []
            for row in result["comparisons"]:
                cells.append(
                    f"{row['difference']:+.3f} [{row['low']:+.3f}, {row['high']:+.3f}]"
                )
            worse = gate_failures(result)
            if arm == "pg":
                failures += [f"{name}: {item}" for item in worse]
            verdict = "; ".join(worse) or "none"
            print(f"| {arm} | {method} | " + " | ".join(cells) + f" | {verdict} |")
    return failures


def main() -> int:
    with (
        closing(sqlite3.connect(f"file:{config.DATABASE}?mode=ro", uri=True)) as lite,
        psycopg.connect(
            config.DATABASE_URL, connect_timeout=config.DATABASE_CONNECT_TIMEOUT_SECONDS
        ) as pg,
    ):
        live = store.live_version(pg)
        if live is None:
            raise SystemExit("no live Postgres index: run `limespec ingest --postgres`")
        copy = copy_sqlite_index(lite, pg)
        pg.commit()
        try:
            arms = {
                "pg": (copy, sqlite_ids(pg, copy, lite)),
                "pg-ingest": (live[0], sqlite_ids(pg, live[0], lite)),
            }
            failures = []
            for name in SETS:
                folder = sets.require(name, sets.ROOT, sets.REGISTRY)
                parts = run_set(folder, llm.embed, lite, pg, arms)
                retrieval.write(parts, OUT / name)
                failures += report(name, parts, arms)
        finally:
            pg.execute("DELETE FROM index_versions WHERE id = %s", (copy,))
            pg.commit()
    if failures:
        print("\nGate X2 (arm pg): FAIL: " + "; ".join(failures))
        return 1
    print("\nGate X2 (arm pg): PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

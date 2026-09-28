"""X2: does the Postgres store rank passages as well as the SQLite store?

    uv run --env-file .env python -m experiments.x2_store_parity

The store is the only difference between the arms. A temporary Postgres index
version is copied from the SQLite index (the same pages, passages and vectors),
each question is embedded once, and that one vector is ranked by both stores.
Vector ranking should match. Keyword ranking is tried two ways: Postgres's
built-in `ts_rank` (arm `pg`, run 1: failed) and BM25 from the pg_textsearch
extension (arm `pg-bm25`, run 2), with one BM25 index per index version so its
word statistics cover that version alone, as SQLite's did. The live Postgres
version, re-embedded by `limespec ingest --postgres`, is reported beside them.
Rankings are scored against the frozen 90 and held-out v2 answer keys; the gate is
that no measure of the gated arm is worse than SQLite beyond the paired bootstrap
interval. The copy and the BM25 indexes are removed at the end. Needs the dev
Postgres (with pg_textsearch) and the embedding server.
"""

import json
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from evaluation import retrieval, sets
from limespec import config, llm, store
from limespec.retrieve import Embed, from_blob, fuse, keyword_ranking, vector_ranking

SETS = ("frozen90", "heldout-v2")
DEPTH = retrieval.DEPTH  # 20 candidates per method, as in the saved runs
METHODS = ("keyword", "vector", "fused")
OUT = Path("data/runs/x2")
GATED_ARM = "pg-bm25"
# How an arm ranks keywords: (connection, version id, question, limit) -> ids
KeywordRanking = Callable[[store.Connection, int, str, int], list[int]]
# Postgres arm -> (version id, {Postgres passage id: SQLite id}, keyword ranking)
Arms = dict[str, tuple[int, dict[int, int], KeywordRanking]]


def bm25_index(version_id: int) -> str:
    return f"x2_bm25_v{version_id}"


def create_bm25_index(pg: store.Connection, version_id: int) -> None:
    """A BM25 index over one version's passages (title and text, as SQLite had).

    A partial index keeps its own word statistics, so scores cover this version
    only. The version id is a literal because the planner must see the predicate.
    """
    pg.execute(
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS {} ON passages "
            "USING bm25 ((title || ' ' || text)) WITH (text_config = 'english') "
            "WHERE index_version_id = {}"
        ).format(sql.Identifier(bm25_index(version_id)), sql.Literal(version_id))
    )


def bm25_ranking(
    pg: store.Connection, version_id: int, question: str, limit: int
) -> list[int]:
    """Passage ids ranked by BM25; passages sharing no word with the question
    score 0 and are left out, as a full-text match would leave them out."""
    score = sql.SQL("(title || ' ' || text) <@> to_bm25query({}, {})").format(
        sql.Literal(question), sql.Literal(bm25_index(version_id))
    )
    rows = pg.execute(
        sql.SQL(
            "SELECT id FROM passages WHERE index_version_id = {} AND {} < 0 "
            "ORDER BY {}, id LIMIT {}"
        ).format(sql.Literal(version_id), score, score, sql.Literal(limit))
    ).fetchall()
    return [row[0] for row in rows]


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
    for arm, (version_id, to_sqlite, rank_keywords) in arms.items():
        keyword = [to_sqlite[i] for i in rank_keywords(pg, version_id, question, DEPTH)]
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
    """Print one set's comparison table; return the gated arm's failures."""
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
            if arm == GATED_ARM:
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
        pg.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
        create_bm25_index(pg, copy)
        create_bm25_index(pg, live[0])
        pg.commit()
        try:
            copy_ids = sqlite_ids(pg, copy, lite)
            live_ids = sqlite_ids(pg, live[0], lite)
            arms: Arms = {
                "pg": (copy, copy_ids, store.keyword_ranking),
                "pg-bm25": (copy, copy_ids, bm25_ranking),
                "pg-bm25-ingest": (live[0], live_ids, bm25_ranking),
            }
            failures = []
            for name in SETS:
                folder = sets.require(name, sets.ROOT, sets.REGISTRY)
                parts = run_set(folder, llm.embed, lite, pg, arms)
                retrieval.write(parts, OUT / name)
                failures += report(name, parts, arms)
        finally:
            pg.rollback()
            for version_id in (copy, live[0]):
                pg.execute(
                    sql.SQL("DROP INDEX IF EXISTS {}").format(
                        sql.Identifier(bm25_index(version_id))
                    )
                )
            pg.execute("DELETE FROM index_versions WHERE id = %s", (copy,))
            pg.commit()
    if failures:
        print(f"\nGate X2 (arm {GATED_ARM}): FAIL: " + "; ".join(failures))
        return 1
    print(f"\nGate X2 (arm {GATED_ARM}): PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

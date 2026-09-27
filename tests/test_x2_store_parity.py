"""The X2 parity machinery: a Postgres copy of a SQLite index ranks by the same
vectors, and every Postgres passage maps back to its SQLite id. Invented pages."""

import sqlite3
from contextlib import closing
from pathlib import Path

from experiments import x2_store_parity as x2
from limespec import store
from limespec.ingest import build_index
from limespec.retrieve import Embed

QUESTION = "Do you deliver on Saturdays?"


def test_a_copy_of_the_sqlite_index_ranks_vectors_identically(
    tmp_path: Path,
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed_1024: Embed,
    pg: store.Connection,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed_1024)
    with closing(sqlite3.connect(database)) as lite:
        copy = x2.copy_sqlite_index(lite, pg)
        mapping = x2.sqlite_ids(pg, copy, lite)
        count = lite.execute("SELECT count(*) FROM passages").fetchone()[0]
        query = fake_embed_1024([QUESTION])[0]

        found = x2.rankings(QUESTION, query, lite, pg, {"pg": (copy, mapping)})

    assert sorted(mapping.values()) == list(range(1, count + 1))
    assert found["pg-vector"] == found["sqlite-vector"]
    assert found["sqlite-keyword"][0] == found["pg-keyword"][0]  # the FAQ answer
    assert set(found) == {f"{arm}-{m}" for arm in ("sqlite", "pg") for m in x2.METHODS}


def test_the_gate_fails_only_when_the_whole_interval_is_below_zero() -> None:
    result = {
        "comparisons": [
            {"pair": "pg vs sqlite", "metric": "a", "difference": -0.1,
             "low": -0.2, "high": -0.01},
            {"pair": "pg vs sqlite", "metric": "b", "difference": -0.05,
             "low": -0.2, "high": 0.1},
        ]
    }  # fmt: skip

    assert x2.gate_failures(result) == ["pg vs sqlite a -0.100"]

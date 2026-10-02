import re
import uuid
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg import sql

from limespec import config, store, telemetry
from limespec.answer import INSUFFICIENT, PARTIAL, SAFETY_REFERRAL
from limespec.ingest import cache_path
from limespec.models import Answer, Claim, Evidence, Passage, Rejection
from limespec.retrieve import Embed, Rerank
from limespec.verify import quote_link

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_URLS = {
    "product.html": "https://example.test/products/mortex",
    "faq.html": "https://example.test/support/faq",
    "category.html": "https://example.test/products/base-coats",
    "article.html": "https://example.test/support/checklist",
}


def word_counts(text: str) -> list[float]:
    """A deterministic stand-in for an embedding: hashed word counts."""
    vector = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32(word.encode()) % 64] += 1
    return vector


@pytest.fixture
def fake_embed() -> Embed:
    return lambda texts: [word_counts(text) for text in texts]


@pytest.fixture
def fake_rerank() -> Rerank:
    """A stand-in reranker: equal scores for every passage keep the fused order."""
    return lambda query, documents: [0.0] * len(documents)


@pytest.fixture
def fixture_pages() -> list[tuple[str, bytes, str]]:
    """(url, raw_bytes, fetched_at) for every hand-written fixture page."""
    return [
        (url, (FIXTURES / name).read_bytes(), "2026-09-12T10:00:00+00:00")
        for name, url in FIXTURE_URLS.items()
    ]


# Invented answers for the interface tests: what `answer()` can return.
MORTEX = Passage(
    1,
    "https://example.test/products/mortex",
    "Mortex Mortar",
    "Uses",
    "Uses\nMortex suits joints of 3 to 6 mm.",
    "2026-09-12T10:00:00+00:00",
)
GUIDE = Passage(
    2,
    "https://example.test/support/guide",
    "Rendering Guide",
    "Drying",
    "Drying\nUneven colour is caused by\nuneven drying.",
    "2026-09-12T10:00:00+00:00",
)


def evidence(passage: Passage, quote: str) -> Evidence:
    return Evidence(
        passage.id,
        passage.url,
        passage.title,
        passage.heading,
        quote,
        quote_link(passage.url, quote),
        passage.fetched_at,
    )


@pytest.fixture
def answered() -> Answer:
    """Two claims sharing one quote, with a removed claim that must never show."""
    joints = evidence(MORTEX, "suits joints of 3 to 6 mm")
    drying = evidence(GUIDE, "Uneven colour is caused by\nuneven drying.")
    return Answer(
        "What joints does Mortex suit?",
        "answered",
        PARTIAL,
        (
            Claim("Mortex suits 3 to 6 mm joints.", (joints,)),
            Claim("Mortex suits thin joints; drying affects colour.", (joints, drying)),
        ),
        (MORTEX, GUIDE),
        (Rejection("Mortex is cheap.", "quote not in S1: 'Mortex is cheap.'"),),
    )


@pytest.fixture
def insufficient() -> Answer:
    return Answer(
        "What does Mortex cost?",
        "insufficient_evidence",
        INSUFFICIENT,
        (),
        (MORTEX, MORTEX, GUIDE),
        (),
    )


@pytest.fixture
def referral() -> Answer:
    return Answer(
        "my son swallowed some mortar", "safety_referral", SAFETY_REFERRAL, (), (), ()
    )


@pytest.fixture(autouse=True)
def no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests reach Postgres only when they set its URL themselves (a throwaway
    database), even when the suite runs with the developer's .env loaded."""
    monkeypatch.setattr(config, "DATABASE_URL", "")


@pytest.fixture(scope="session")
def span_store() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    telemetry.tracers.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def spans(span_store: InMemorySpanExporter) -> InMemorySpanExporter:
    """Every span finished during the test, oldest first."""
    span_store.clear()
    return span_store


MetricPoints = Callable[[str], list[Any]]


@pytest.fixture
def metric_points(monkeypatch: pytest.MonkeyPatch) -> MetricPoints:
    """A function giving the data points recorded so far for one metric name."""
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(
        telemetry, "metrics", telemetry.instruments(meters.get_meter("t"))
    )

    def points(name: str) -> list[Any]:
        found: list[Any] = []
        data = reader.get_metrics_data()
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name == name:
                        found.extend(metric.data.data_points)
        return found

    return points


# Postgres tests run against the development server started with
# `docker compose -f deploy/compose.yaml --profile dev up -d` (settings in
# deploy/.env), in a throwaway database, so development data is never touched.
REPOSITORY = Path(__file__).parent.parent
MIGRATIONS = REPOSITORY / "db" / "migrations"


def server_url(database: str) -> str:
    settings = {}
    for line in (
        (REPOSITORY / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    ):
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            settings[key] = value
    user, password = settings["POSTGRES_USER"], settings["POSTGRES_PASSWORD"]
    return f"postgresql://{user}:{password}@127.0.0.1:5432/{database}"


def migration_up(path: Path) -> str:
    """The SQL between a dbmate migration's `-- migrate:up` and `-- migrate:down`."""
    text = path.read_text(encoding="utf-8")
    return text.split("-- migrate:up", 1)[1].split("-- migrate:down", 1)[0]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A fresh database with every migration applied, dropped after the session."""
    name = f"limespec_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(server_url("postgres"), autocommit=True)
    except psycopg.OperationalError as error:
        pytest.fail(
            "the development Postgres is not running; start it with "
            f"`docker compose -f deploy/compose.yaml --profile dev up -d` ({error})"
        )
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(server_url(name)) as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration_up(path).encode())
    yield server_url(name)
    with psycopg.connect(server_url("postgres"), autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )


@pytest.fixture
def pg(postgres_url: str) -> Iterator[store.Connection]:
    """A connection to the test database, emptied after each test."""
    with psycopg.connect(postgres_url) as conn:
        yield conn
        conn.rollback()
        conn.execute(
            "TRUNCATE answers, conversations, passages, index_versions, documents, "
            "images RESTART IDENTITY"
        )
        # Each index version has its own BM25 index; the next test starts at version 1.
        for (name,) in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'passages_bm25_v%'"
        ).fetchall():
            conn.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(name)))


@pytest.fixture
def fake_embed_1024(fake_embed: Embed) -> Embed:
    """The word-count stand-in, padded to the Postgres column's 1024 dimensions."""
    return lambda texts: [v + [0.0] * (1024 - len(v)) for v in fake_embed(texts)]


@pytest.fixture
def cached_faq(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sources file naming the FAQ fixture, already in a temporary page cache."""
    url = FIXTURE_URLS["faq.html"]
    sources = tmp_path / "sources.txt"
    sources.write_text(f"{url}\n")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path / "site")
    monkeypatch.setattr(config, "SOURCES_FILE", sources)
    cache_path(url).parent.mkdir()
    cache_path(url).write_bytes((FIXTURES / "faq.html").read_bytes())
    return sources

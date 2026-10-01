import json
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from limespec import acquire, assistant, cli, config, documents, llm, store, telemetry
from limespec.app import app
from limespec.ingest import ingest
from limespec.models import Answer
from limespec.retrieve import Embed, Rerank


def test_search_prints_ranked_passages_with_their_pages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cached_faq: Path,
    postgres_url: str,
    pg: store.Connection,
    fake_embed_1024: Embed,
    fake_rerank: Rerank,
) -> None:
    ingest(pg, fake_embed_1024)
    pg.commit()
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    monkeypatch.setattr(llm, "rerank", fake_rerank)

    assert cli.main(["search", "Do you deliver on Saturdays?"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("1. Questions › Do you deliver on Saturdays?")
    assert "https://example.test/support/faq" in output


def test_search_without_a_live_index_explains_what_to_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    postgres_url: str,
    pg: store.Connection,
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)

    assert cli.main(["search", "anything"]) == 1
    assert "no live Postgres index" in capsys.readouterr().err


def test_ask_prints_the_answer_then_numbered_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answered: Answer,
) -> None:
    monkeypatch.setattr(assistant, "ask", lambda question: answered)

    assert cli.main(["ask", "What joints does Mortex suit?"]) == 0
    output = capsys.readouterr().out
    assert output.startswith(
        "Answer:\n"
        "1. Mortex suits 3 to 6 mm joints. [1]\n"
        "2. Mortex suits thin joints; drying affects colour. [1] [2]\n"
        "\nNote:\nOnly statements verified"
    )
    assert "Sources:\n[1] Mortex Mortar › Uses (captured 2026-09-12)\n" in output
    assert '    "suits joints of 3 to 6 mm"\n' in output
    assert "Mortex is cheap" not in output


def test_a_refusal_prints_the_fixed_text_and_closest_pages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    insufficient: Answer,
) -> None:
    monkeypatch.setattr(assistant, "ask", lambda question: insufficient)

    assert cli.main(["ask", "What does Mortex cost?"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("Answer:\nI could not find enough support")
    assert (
        "Closest pages:\n- Mortex Mortar: https://example.test/products/mortex"
        in output
    )


def test_ask_without_a_question_prompts_like_the_brief(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    referral: Answer,
) -> None:
    prompts: list[str] = []
    asked: list[str] = []

    def typed(prompt: str) -> str:
        prompts.append(prompt)
        return "  my son swallowed some mortar  "

    def ask(question: str) -> Answer:
        asked.append(question)
        return referral

    monkeypatch.setattr("builtins.input", typed)
    monkeypatch.setattr(assistant, "ask", ask)

    assert cli.main(["ask"]) == 0
    assert prompts == ["Ask a question: "]
    assert asked == ["my son swallowed some mortar"]
    assert capsys.readouterr().out.startswith("Answer:\nThis may be an emergency.")


def test_a_blank_question_asks_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "   ")

    assert cli.main(["ask"]) == 0
    assert capsys.readouterr().out == "No question asked.\n"


def test_serve_runs_the_web_page_on_this_machine_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        uvicorn, "run", lambda served, **options: calls.append((served, options))
    )

    assert cli.main(["serve"]) == 0
    assert cli.main(["serve", "--port", "8123"]) == 0
    logging = {"log_config": telemetry.LOG_CONFIG, "access_log": False}
    assert calls == [
        (app, {"host": "127.0.0.1", "port": 8090, **logging}),
        (app, {"host": "127.0.0.1", "port": 8123, **logging}),
    ]


def test_ingest_needs_its_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", "")

    assert cli.main(["ingest"]) == 1
    assert "LIMESPEC_DATABASE_URL is not set" in capsys.readouterr().err


def test_ingest_writes_a_live_version_and_prints_its_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cached_faq: Path,
    postgres_url: str,
    pg: store.Connection,
    fake_embed_1024: Embed,
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)

    assert cli.main(["ingest"]) == 0
    live = store.live_version(pg)
    assert live is not None
    output = capsys.readouterr().out
    assert output.startswith(f"index version: {live[0]} (live)\n")
    assert "passages: 2" in output


def test_ingest_can_build_from_another_list_without_going_live(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cached_faq: Path,
    postgres_url: str,
    pg: store.Connection,
    fake_embed_1024: Embed,
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    candidates = cached_faq.parent / "candidates.txt"
    candidates.write_text(cached_faq.read_text())

    assert cli.main(["ingest", "--sources", str(candidates), "--no-live"]) == 0
    assert store.live_version(pg) is None
    [(version,)] = pg.execute("SELECT id FROM index_versions").fetchall()
    assert capsys.readouterr().out.startswith(
        f"index version: {version} (not live; serve it with "
        f"LIMESPEC_INDEX_VERSION={version})\n"
    )


def test_ingest_can_add_every_page_and_the_pdf_readings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cached_faq: Path,
    postgres_url: str,
    pg: store.Connection,
    fake_embed_1024: Embed,
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(llm, "embed", fake_embed_1024)
    url = "https://example.test/duro.pdf"
    document = (
        (url, "Duro", "2026-09-12T10:00:00+00:00", "sha-pdf"),
        [(url, "Duro", "Mixing", "Mix well.", "Mixing", 1)],
    )
    asked = []

    def index_documents(form: str, titles: dict[str, str]) -> Any:
        asked.append(form)
        return [document]

    monkeypatch.setattr(documents, "index_documents", index_documents)

    arguments = ["ingest", "--no-live", "--all-pages", "--pdf-form", "rows"]
    assert cli.main(arguments) == 0
    assert asked == ["rows"]
    assert "passages: 3" in capsys.readouterr().out


def test_an_unreachable_postgres_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cached_faq: Path,
) -> None:
    # Nothing listens on port 9; on Windows the attempt waits out the timeout.
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://x:y@127.0.0.1:9/z")
    monkeypatch.setattr(config, "DATABASE_CONNECT_TIMEOUT_SECONDS", 1)

    assert cli.main(["ingest"]) == 1
    assert capsys.readouterr().err.startswith("error: cannot reach the Postgres index")


def test_model_server_errors_are_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    postgres_url: str,
) -> None:
    def failing_ingest(
        conn: store.Connection, embed: Embed, *rest: Any
    ) -> tuple[int, dict[str, str]]:
        raise llm.ModelServerError("embedding server at http://127.0.0.1:8081 failed")

    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)
    monkeypatch.setattr(cli, "ingest", failing_ingest)

    assert cli.main(["ingest"]) == 1
    assert "embedding server" in capsys.readouterr().err


def test_read_images_stores_pictures_then_reads_each_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from PIL import Image

    from limespec import images

    out = tmp_path / "images"
    out.mkdir()
    Image.new("RGB", (8, 8), "white").save(out / "p1.png")
    Image.new("RGB", (8, 8), "white").save(out / "p2.png")
    (out / "p2.json").write_text("{}")  # read before
    readings = tmp_path / "elements"
    readings.mkdir()
    (readings / "r.json").write_text(json.dumps({"urls": ["u"], "elements": []}))
    (readings / "report.json").write_text("{}")
    records = [
        {"url": "https://x.test/a.png", "sha256": "a", "content_type": "image/png"},
        {"url": "https://x.test/d.docx", "sha256": "d", "content_type": documents.WORD},
    ]
    seen: dict[str, Any] = {}

    def collect(pages: Any, found: Any, stored: Any, folder: Path) -> list[Any]:
        seen["stored"] = stored
        return [{"id": "p1"}, {"id": "p2"}, {"id": "p1"}]

    monkeypatch.setattr(config, "IMAGES", out)
    monkeypatch.setattr(documents, "OUT", readings)
    monkeypatch.setattr(acquire, "read_manifest", lambda: records)
    monkeypatch.setattr(cli, "site_html", lambda: [("https://x.test/", "<html/>")])
    monkeypatch.setattr(images, "collect", collect)
    monkeypatch.setattr(images, "read_text", lambda image, url: "Duro 25kg")
    monkeypatch.setattr(llm, "healthy", lambda url: url == "http://vlm")

    assert cli.main(["read-images", "--vlm", "http://none"]) == 1
    assert cli.main(["read-images", "--vlm", "http://vlm"]) == 0

    assert json.loads((out / "p1.json").read_text())["ocr"] == "Duro 25kg"
    assert seen["stored"]["https://x.test/d.docx"] == readings / "rendered" / "d.pdf"
    assert "3 places of 2 pictures; 1 read now" in capsys.readouterr().out

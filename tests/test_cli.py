from pathlib import Path
from typing import Any

import pytest
import uvicorn

from limespec import assistant, cli, config, llm
from limespec.app import app
from limespec.ingest import build_index
from limespec.models import Answer
from limespec.retrieve import Embed, Rerank


def test_ingest_prints_the_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "ingest", lambda embed: {"pages": "68"})

    assert cli.main(["ingest"]) == 0
    assert "pages: 68" in capsys.readouterr().out


def test_search_prints_ranked_passages_with_their_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixture_pages: list[tuple[str, bytes, str]],
    fake_embed: Embed,
    fake_rerank: Rerank,
) -> None:
    database = tmp_path / "index.db"
    build_index(database, fixture_pages, fake_embed)
    monkeypatch.setattr(config, "DATABASE", database)
    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(llm, "rerank", fake_rerank)

    assert cli.main(["search", "Do you deliver on Saturdays?"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("1. Questions › Do you deliver on Saturdays?")
    assert "https://example.test/support/faq" in output


def test_search_without_an_index_explains_what_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "DATABASE", tmp_path / "missing.db")

    assert cli.main(["search", "anything"]) == 1
    assert "run `limespec ingest` first" in capsys.readouterr().err


def test_a_damaged_index_is_an_operational_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "damaged.db"
    database.write_bytes(b"not a SQLite database")
    monkeypatch.setattr(config, "DATABASE", database)

    assert cli.main(["ask", "anything"]) == 1
    assert "run `limespec ingest` to rebuild it" in capsys.readouterr().err


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
    assert calls == [
        (app, {"host": "127.0.0.1", "port": 8090}),
        (app, {"host": "127.0.0.1", "port": 8123}),
    ]


def test_model_server_errors_are_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_ingest(embed: Embed) -> dict[str, str]:
        raise llm.ModelServerError("embedding server at http://127.0.0.1:8081 failed")

    monkeypatch.setattr(cli, "ingest", failing_ingest)

    assert cli.main(["ingest"]) == 1
    assert "embedding server" in capsys.readouterr().err

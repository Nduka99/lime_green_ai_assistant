"""The web page and JSON endpoint, compared with the CLI."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from limespec import assistant, cli
from limespec.app import app
from limespec.llm import ModelServerError
from limespec.models import Answer
from limespec.view import view

client = TestClient(app)


def answers_with(monkeypatch: pytest.MonkeyPatch, result: Answer) -> list[str]:
    """Make every question get `result`; returns the questions asked."""
    asked: list[str] = []

    def ask(question: str) -> Answer:
        asked.append(question)
        return result

    monkeypatch.setattr(assistant, "ask", ask)
    return asked


def test_the_page_starts_with_an_empty_form() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<form method="get" action="/">' in response.text
    # While an answer loads, the button is disabled and this line is shown.
    assert '<p id="answering" class="muted" hidden>Answering…' in response.text
    assert "Sources" not in response.text


def test_an_answer_shows_claims_quotes_links_and_the_caution(
    monkeypatch: pytest.MonkeyPatch, answered: Answer
) -> None:
    asked = answers_with(monkeypatch, answered)

    response = client.get("/", params={"q": "  What joints does Mortex suit?  "})

    assert asked == ["What joints does Mortex suit?"]
    page = response.text
    assert response.status_code == 200
    assert "Mortex suits 3 to 6 mm joints." in page
    assert '<a href="#source-2">[2]</a>' in page
    assert "“suits joints of 3 to 6 mm”" in page
    assert "https://example.test/products/mortex#:~:text=" in page
    assert "captured 2026-09-12" in page
    assert "Only statements verified" in page
    assert "Mortex is cheap" not in page  # removed claims are never shown


def test_a_referral_shows_each_line_of_the_fixed_text(
    monkeypatch: pytest.MonkeyPatch, referral: Answer
) -> None:
    answers_with(monkeypatch, referral)

    page = client.get("/", params={"q": "my son swallowed some mortar"}).text

    assert "Safety referral" in page
    for line in referral.notice.splitlines():
        if line.startswith("- "):  # the steps are a list
            assert f"<li>{escape(line[2:])}</li>" in page
        else:
            assert f"<p>{escape(line)}</p>" in page
    assert page.count("<ul>") == 1  # the four NHS steps form one list
    assert "<h2>Sources</h2>" not in page


def test_a_refusal_lists_the_closest_pages(
    monkeypatch: pytest.MonkeyPatch, insufficient: Answer
) -> None:
    answers_with(monkeypatch, insufficient)

    page = client.get("/", params={"q": "What does Mortex cost?"}).text

    assert "Not enough information" in page
    assert '<a href="https://example.test/support/guide">Rendering Guide</a>' in page


def test_an_operational_error_is_a_clear_503_not_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(question: str) -> Answer:
        raise ModelServerError("generation server at http://127.0.0.1:8080 failed")

    monkeypatch.setattr(assistant, "ask", unavailable)

    page = client.get("/", params={"q": "anything"})
    api = client.get("/api/answer", params={"q": "anything"})

    assert page.status_code == 503 and "generation server" in page.text
    assert api.status_code == 503 and "generation server" in api.json()["detail"]


def test_a_damaged_index_is_a_clear_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "damaged.db"
    database.write_bytes(b"not a SQLite database")
    monkeypatch.setattr("limespec.config.DATABASE", database)

    response = client.get("/api/answer", params={"q": "anything"})

    assert response.status_code == 503
    assert "run `limespec ingest` to rebuild it" in response.json()["detail"]


def test_the_question_is_escaped_in_the_page(
    monkeypatch: pytest.MonkeyPatch, insufficient: Answer
) -> None:
    answers_with(monkeypatch, insufficient)

    page = client.get("/", params={"q": "<script>alert(1)</script>"}).text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_the_api_returns_the_reader_view_as_json(
    monkeypatch: pytest.MonkeyPatch, answered: Answer
) -> None:
    answers_with(monkeypatch, answered)

    response = client.get("/api/answer", params={"q": "What joints does Mortex suit?"})

    assert response.status_code == 200
    assert response.json() == view(answered)


def test_the_api_needs_a_question() -> None:
    assert client.get("/api/answer", params={"q": "  "}).status_code == 400


def test_cli_and_http_show_the_same_answer_for_the_same_question(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answered: Answer,
) -> None:
    asked = answers_with(monkeypatch, answered)

    assert cli.main(["ask", "What joints does Mortex suit?"]) == 0
    printed = capsys.readouterr().out
    api = client.get("/api/answer", params={"q": "What joints does Mortex suit?"})
    page = client.get("/", params={"q": "What joints does Mortex suit?"}).text

    assert asked == ["What joints does Mortex suit?"] * 3
    # The CLI's text is exactly the text built from the API's JSON.
    assert printed.rstrip("\n") == cli.render_text(api.json())
    for claim in api.json()["claims"]:
        assert claim["text"] in page
    for source in api.json()["sources"]:
        assert source["title"] in page and source["quote"] in page

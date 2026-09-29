"""The harness's safeguards and plumbing: hashed sets, key checks, the HTTP runner
and the command line. Every set and page here is invented."""

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import ask, keys, retrieval, sets

URL = "https://example.test/products/mortex"
PAGE = (
    '<html><body><script>var hidden = "suits joints";</script>'
    "<p>Mortex suits joints of <b>3 to 6</b> mm.</p>"
    '<img src="a.jpg" alt="Mortex on a stone wall"><img src="b.jpg"></body></html>'
)


def case(case_id: str, status: str, quote: str, kind: str = "") -> dict[str, Any]:
    evidence = {"page_url": URL, "quote": quote, **({"kind": kind} if kind else {})}
    return {
        "id": case_id,
        "type": "single",
        "expected_status": status,
        "parts": [{"id": "p1", "evidence": [evidence]}],
        "wordings": [
            {"style": "original", "text": f"{case_id} original?"},
            {"style": "rushed", "text": f"{case_id} rushed?"},
        ],
    }


KEY = {
    "cases": [
        case("joints", "answered", "suits joints of 3 to 6 mm."),
        case("photo", "answered", "Mortex on a stone wall", kind="image_alt"),
    ]
}


def read_page(url: str) -> str | None:
    return PAGE if url == URL else None


def test_a_good_key_has_no_problems() -> None:
    assert keys.problems(KEY, read_page) == ([], set())


def test_key_problems_are_all_reported() -> None:
    uncached = {"url": "https://example.test/gone", "quote": "x"}
    bad = {
        "cases": [
            case("joints", "answered", "suits joints of 3 to 60 mm"),
            case("joints", "maybe", "Mortex on brick", kind="image_alt"),
            {**case("rushed", "answered", ""), "wordings": [{"style": "rushed"}]},
            {**case("gone", "answered", "x"), "parts": [{"evidence": [uncached]}]},
        ]
    }

    found, missing = keys.problems(bad, read_page)

    assert found == [
        "case ids are not unique",
        f"joints p1: a quote is not on {URL}",
        "joints: unknown expected_status",
        f"joints p1: a quote is not on {URL}",  # no image has this alt text
        "rushed: wordings are ['rushed'], not ['original', 'rushed']",
        f"rushed p1: a quote is not on {URL}",  # an empty quote never matches
    ]
    assert missing == {"https://example.test/gone"}


def test_script_text_is_not_page_text() -> None:
    assert "hidden" not in keys.page_text(PAGE)
    assert keys.alt_texts(PAGE) == ["mortex on a stone wall", ""]


def test_blind_questions_are_shuffled_the_same_way_every_time() -> None:
    first = keys.blind_questions(KEY, seed=7, prefix="t")
    assert first == keys.blind_questions(KEY, seed=7, prefix="t")
    assert [row["id"] for row in first] == ["t001", "t002", "t003", "t004"]
    assert sorted(row["question"] for row in first) == sorted(
        w["text"] for c in KEY["cases"] for w in c["wordings"]
    )


def make_set(root: Path) -> Path:
    folder = root / "demo"
    (folder / "retrieval").mkdir(parents=True)
    (folder / "key.json").write_text(json.dumps(KEY))
    rows = keys.blind_questions(KEY, seed=7, prefix="t")
    (folder / "questions.json").write_text(json.dumps({"questions": rows}))
    parts = [retrieval.Part("t001p1", "t001", frozenset({1}), {"fused": [1]})]
    retrieval.write(parts, folder / "retrieval")
    return folder


def test_registering_hashes_every_file_and_verify_finds_no_problem(
    tmp_path: Path,
) -> None:
    make_set(tmp_path)
    registry = tmp_path / "sets.json"

    added = sets.register("demo", "invented", tmp_path, registry)

    assert added == ["key.json", "questions.json", "retrieval/qrels.txt",
                     "retrieval/run-fused.txt"]  # fmt: skip
    assert sets.problems("demo", tmp_path, registry) == []
    assert sets.require("demo", tmp_path, registry) == tmp_path / "demo"
    assert json.loads(registry.read_text())["sets"]["demo"]["description"] == "invented"


def test_a_changed_missing_or_new_file_is_caught(tmp_path: Path) -> None:
    folder = make_set(tmp_path)
    registry = tmp_path / "sets.json"
    sets.register("demo", "invented", tmp_path, registry)
    (folder / "key.json").write_text("{}")
    (folder / "questions.json").unlink()
    (folder / "extra.json").write_text("[]")

    assert sets.problems("demo", tmp_path, registry) == [
        "demo/questions.json: missing",
        "demo/key.json: changed since it was registered",
        "demo/extra.json: not registered",
    ]
    with pytest.raises(ValueError, match="changed since it was registered"):
        sets.require("demo", tmp_path, registry)


def test_a_registered_file_can_never_be_replaced(tmp_path: Path) -> None:
    folder = make_set(tmp_path)
    registry = tmp_path / "sets.json"
    sets.register("demo", "invented", tmp_path, registry)
    (folder / "key.json").write_text("{}")

    with pytest.raises(ValueError, match="key.json: changed"):
        sets.register("demo", "invented", tmp_path, registry)


def test_new_files_can_be_added_to_a_registered_set(tmp_path: Path) -> None:
    folder = make_set(tmp_path)
    registry = tmp_path / "sets.json"
    sets.register("demo", "invented", tmp_path, registry)
    (folder / "sitting").mkdir()
    (folder / "sitting" / "grades.json").write_text("{}")

    assert sets.register("demo", "", tmp_path, registry) == ["sitting/grades.json"]
    assert sets.problems("demo", tmp_path, registry) == []


def test_an_unregistered_set_is_refused(tmp_path: Path) -> None:
    assert sets.read_registry(tmp_path / "none.json") == {"sets": {}}
    assert sets.problems("demo", tmp_path, tmp_path / "none.json") == [
        "demo: not registered"
    ]


def answer_view(question: str) -> dict[str, Any]:
    return {"question": question, "status": "answered", "notice": "", "claims": []}


def endpoint(request: httpx.Request) -> httpx.Response:
    """A stand-in deployment of both APIs (v1 takes JSON, v5 a query string): one
    question fails, one cannot be reached."""
    if request.method == "POST":
        question = json.loads(request.content)["question"]
    else:
        question = request.url.params["q"]
    if "rushed" in question and "joints" in question:
        return httpx.Response(503, text="the model server is down")
    if "photo rushed" in question:
        raise httpx.ConnectError("refused")
    if request.method == "POST":
        return httpx.Response(200, json={"id": 7, "answer": answer_view(question)})
    return httpx.Response(200, json=answer_view(question))


def test_ask_saves_views_errors_and_resumes(tmp_path: Path) -> None:
    out = tmp_path / "runs" / "answers-v5.json"
    questions = keys.blind_questions(KEY, seed=7, prefix="t")
    client = httpx.Client(
        base_url="http://app.test", transport=httpx.MockTransport(endpoint)
    )

    records = ask.ask_all(questions[:2], client, "/api/answer", out)
    records = ask.ask_all(questions, client, "/api/answer", out)

    assert [r["id"] for r in records] == ["t001", "t002", "t003", "t004"]
    by_question = {r["question"]: r for r in records}
    assert by_question["joints original?"]["view"]["status"] == "answered"
    assert by_question["joints rushed?"] == {
        "id": by_question["joints rushed?"]["id"],
        "question": "joints rushed?",
        "http": 503,
        "error": "the model server is down",
        "seconds": by_question["joints rushed?"]["seconds"],
    }
    assert by_question["photo rushed?"]["http"] is None
    assert json.loads(out.read_text()) == records


def test_ask_posts_to_the_v1_api_and_keeps_the_audit_record_id(
    tmp_path: Path,
) -> None:
    out = tmp_path / "runs" / "answers-platform.json"
    questions = keys.blind_questions(KEY, seed=7, prefix="t")
    client = httpx.Client(
        base_url="http://app.test", transport=httpx.MockTransport(endpoint)
    )

    records = ask.ask_all(questions, client, "/api/v1/answers", out)

    by_question = {r["question"]: r for r in records}
    answered = by_question["joints original?"]
    assert (answered["view"]["status"], answered["answer_id"]) == ("answered", 7)
    assert by_question["joints rushed?"]["http"] == 503


def run(capsys: pytest.CaptureFixture[str], root: Path, *argv: str) -> tuple[int, str]:
    code = cli.main(
        ["--root", str(root), "--registry", str(root / "sets.json"),
         "--runs", str(root / "runs"), *argv]
    )  # fmt: skip
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_command_line_registers_verifies_and_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_set(tmp_path)
    sitting = folder / "sitting"
    sitting.mkdir()
    questions = json.loads((folder / "questions.json").read_text())["questions"]
    (sitting / "grades.json").write_text(
        json.dumps({row["id"]: {"v5": {"verdict": "sound"}} for row in questions})
    )
    records = [
        {"id": row["id"], "view": answer_view(row["question"]), "seconds": 2.0}
        for row in questions
    ]
    (sitting / "answers-v5.json").write_text(json.dumps(records))

    assert run(capsys, tmp_path, "register", "demo") == (
        0,
        "demo: 6 files registered\n",
    )
    assert run(capsys, tmp_path, "verify")[1].endswith("1 sets checked, 0 problems\n")
    code, text = run(capsys, tmp_path, "retrieval", "demo")
    assert code == 0 and text.startswith("demo: 1 questions, 1 question parts")
    code, text = run(capsys, tmp_path, "retrieval", "demo", "--json")
    assert json.loads(text)["parts"] == 1
    code, text = run(capsys, tmp_path, "grades", "demo", "sitting")
    assert code == 0 and "| All | 4 | 4 / 0 / 0 / 0 |" in text
    code, text = run(capsys, tmp_path, "grades", "demo", "sitting", "--json")
    assert json.loads(text)["status_matched"] == {"v5": 4}


def test_command_line_reports_problems_and_refuses_changed_sets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_set(tmp_path)
    run(capsys, tmp_path, "register", "demo")
    (folder / "key.json").write_text("{}")

    code, text = run(capsys, tmp_path, "verify", "demo")
    assert code == 1 and "PROBLEM demo/key.json: changed" in text
    code, text = run(capsys, tmp_path, "retrieval", "demo")
    assert code == 1 and text.startswith("error: demo/key.json: changed")


def test_command_line_checks_a_key_and_writes_the_blind_file_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = tmp_path / "site"
    pages.mkdir()
    (pages / "products__mortex.html").write_text(PAGE)
    folder = tmp_path / "new"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(KEY))
    args = ["check-key", "new", "--seed", "7", "--prefix", "t", "--pages", str(pages)]

    code, text = run(capsys, tmp_path, *args)
    assert code == 0 and "blind file written" in text
    assert json.loads((folder / "questions.json").read_text())["questions"] == (
        keys.blind_questions(KEY, seed=7, prefix="t")
    )
    code, text = run(capsys, tmp_path, *args)
    assert code == 1 and "blind file not written" in text


def test_command_line_reports_wrong_quotes_and_uncached_pages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = tmp_path / "site"
    pages.mkdir()
    (pages / "products__mortex.html").write_text(PAGE)
    uncached = {**case("gone", "answered", "x")}
    uncached["parts"] = [
        {"evidence": [{"url": "https://example.test/gone", "quote": "x"}]}
    ]
    key = {"cases": [case("joints", "answered", "3 to 60 mm"), uncached]}
    folder = tmp_path / "new"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(key))

    code, text = run(capsys, tmp_path, "check-key", "new", "--seed", "1", "--prefix",
                     "t", "--pages", str(pages))  # fmt: skip

    assert code == 1
    assert f"PROBLEM joints p1: a quote is not on {URL}" in text
    assert "NOT CACHED https://example.test/gone" in text
    assert not (folder / "questions.json").exists()
    assert cli.page_reader(tmp_path)("https://example.test/") is None


def test_command_line_asks_a_deployed_endpoint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_set(tmp_path)
    run(capsys, tmp_path, "register", "demo")
    real_client = httpx.Client

    def client(**options: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(endpoint), **options)

    monkeypatch.setattr(httpx, "Client", client)

    code, text = run(capsys, tmp_path, "ask", "demo", "--target", "http://app.test",
                     "--run", "v5")  # fmt: skip

    assert code == 1  # two of the four answers are errors
    assert "4 answers saved" in text and "2 errors" in text
    saved = json.loads((tmp_path / "runs" / "demo" / "answers-v5.json").read_text())
    assert len(saved) == 4


def test_command_line_ask_succeeds_when_every_answer_arrives(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_set(tmp_path)
    run(capsys, tmp_path, "register", "demo")
    real_client = httpx.Client

    def working(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answer_view(request.url.params["q"]))

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **options: real_client(
            transport=httpx.MockTransport(working), **options
        ),
    )

    code, text = run(capsys, tmp_path, "ask", "demo", "--target", "http://app.test",
                     "--run", "v5", "--endpoint", "/api/answer")  # fmt: skip

    assert code == 0 and "0 errors" in text


def test_the_module_runs_as_a_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "sets.json"
    monkeypatch.setattr(
        sys, "argv", ["evaluation", "--registry", str(registry), "verify"]
    )
    # The tests imported the module already; run it fresh, as `python -m` would.
    monkeypatch.delitem(sys.modules, "evaluation.__main__")

    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("evaluation", run_name="__main__")
    assert stopped.value.code == 0

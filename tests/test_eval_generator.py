"""X39's harness: requests, passes, comparisons, the degradation curve and prompt
reuse. Servers, audit records and keys are invented."""

import json
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import generator, sets
from limespec import answer, assistant, config, store
from limespec.models import Passage

URL = "http://127.0.0.1:8083/v1/chat/completions"


def passage(passage_id: int, text: str) -> Passage:
    return Passage(passage_id, f"https://example.test/{passage_id}", "Duro", "", text,
                   "2026-09-29T10:00:00+00:00")  # fmt: skip


def timings(prompt_ms: float, predicted_ms: float, **more: int) -> dict[str, Any]:
    return {"prompt_n": 100, "prompt_ms": prompt_ms, "predicted_n": 10,
            "predicted_ms": predicted_ms, "cache_n": 0, **more}  # fmt: skip


def reply(
    reply_id: str, content: str = "{}", total_ms: float = 1000.0
) -> dict[str, Any]:
    return {"id": reply_id, "content": content, "finish": "stop",
            "timings": timings(total_ms / 2, total_ms / 2)}  # fmt: skip


def chat_response(content: str, finish: str = "stop", **body: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}, "finish_reason": finish}],
              **body},
        request=httpx.Request("POST", URL),
    )  # fmt: skip


# Replay requests (M2).


def test_replayed_records_are_answers_drawn_by_seed_with_the_warm_up_first() -> None:
    records: list[dict[str, Any]] = [
        {"id": f"q{i}", "answer_id": i, "view": {"status": "answered"}}
        for i in range(1, 60)
    ]
    records += [
        {"id": "e", "answer_id": 99, "view": {"status": "safety_referral"}},
        {"id": "x", "http": None, "error": "refused"},
    ]

    drawn = generator.replay_ids(records, size=10)

    assert len(drawn) == 11 and len(set(drawn)) == 11
    assert 99 not in drawn
    assert drawn == generator.replay_ids(list(reversed(records)), size=10)


def test_an_answer_request_is_the_assistant_s_own() -> None:
    passages = [passage(7, "Duro is free of cement."), passage(3, "Joints of 6 mm.")]

    request = generator.answer_request("a1", "What is in Duro?", passages)

    sources = dict(zip(["S1", "S2"], passages, strict=True))
    assert request == {
        "id": "a1",
        "system": answer.ANSWER_PROMPT,
        "user": answer.user_prompt("What is in Duro?", sources),
        "schema": answer.answer_schema(["S1", "S2"]),
        "passage_ids": [7, 3],
    }


def test_a_request_is_sent_with_the_assistant_s_body_and_its_timings_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MODEL_API_KEY", "secret")
    sent: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append({"url": url, **kwargs})
        return chat_response('{"a": 1}', timings=timings(10, 20))

    request = {"id": "r1", "system": "s", "user": "u", "schema": {"type": "object"}}
    found = generator.send(URL, {**request, "max_tokens": 1}, False, post)
    plain = generator.send(
        URL, request, True, lambda url, **kw: chat_response("{}", "length")
    )

    payload = sent[0]["json"]
    assert payload["cache_prompt"] is False and payload["max_tokens"] == 1
    assert payload["messages"][1] == {"role": "user", "content": "u"}
    assert sent[0]["headers"] == {"Authorization": "Bearer secret"}
    assert found["content"] == '{"a": 1}' and found["finish"] == "stop"
    assert found["timings"]["prompt_ms"] == 10 and found["wall_seconds"] >= 0
    assert plain["timings"] == {} and plain["finish"] == "length"


def test_gpu_memory_is_read_from_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[0] == "nvidia-smi"
        return subprocess.CompletedProcess(command, 0, stdout="6271\n")

    monkeypatch.setattr(subprocess, "run", run)

    assert generator.gpu_used_mib() == 6271.0


def test_memory_samples_read_the_machine_and_given_a_process_the_server() -> None:
    machine = generator.memory_sample(None, lambda: 100.0)
    server = generator.memory_sample(os.getpid(), lambda: 100.0)

    assert set(machine) == {"gpu_mib", "available_mib"}
    assert machine["gpu_mib"] == 100.0 and machine["available_mib"] > 0
    assert {"server_mib", "server_private_mib", "server_peak_mib"} <= set(server)
    assert server["server_peak_mib"] >= server["server_mib"] > 0


def test_a_pass_sends_the_warm_up_first_and_keeps_memory_extremes() -> None:
    order: list[str] = []
    readings = iter([
        {"gpu_mib": 5000.0, "available_mib": 9000.0},
        {"gpu_mib": 7000.0, "available_mib": 8000.0},
    ])  # fmt: skip

    def post(url: str, **kwargs: Any) -> httpx.Response:
        order.append(kwargs["json"]["messages"][1]["content"])
        return chat_response("{}", timings=timings(1, 1))

    def sample() -> dict[str, float]:
        return next(readings, {"gpu_mib": 6000.0, "available_mib": 8500.0})

    request = {"system": "s", "schema": {}}
    requests = {
        "warm_up": [{**request, "id": "w", "user": "warm"}],
        "requests": [{**request, "id": "r", "user": "real"}],
    }

    found = generator.run_pass(URL, requests, False, sample, post)

    assert order == ["warm", "real"]
    assert [r["id"] for r in found["warm_up"]] == ["w"]
    assert [r["id"] for r in found["replies"]] == ["r"]
    assert found["memory"]["gpu_mib"] >= 5000.0
    assert found["memory"]["available_mib"] <= 9000.0
    assert found["wall_seconds"] >= 0


def test_a_pass_can_send_requests_together_and_keeps_their_order() -> None:
    both_in = threading.Barrier(2, timeout=5)

    def post(url: str, **kwargs: Any) -> httpx.Response:
        both_in.wait()  # returns only when two requests are in flight at once
        return chat_response(kwargs["json"]["messages"][1]["content"],
                             timings=timings(1, 1))  # fmt: skip

    request = {"system": "s", "schema": {}}
    requests = {
        "warm_up": [],
        "requests": [{**request, "id": n, "user": n} for n in ("a", "b", "c", "d")],
    }

    found = generator.run_pass(URL, requests, False, dict, post, concurrency=2)

    assert [r["id"] for r in found["replies"]] == ["a", "b", "c", "d"]


def test_extremes_are_peaks_except_the_lowest_available_memory() -> None:
    samples = [
        {"gpu_mib": 1.0, "available_mib": 9.0, "server_mib": 3.0},
        {"gpu_mib": 2.0, "available_mib": 7.0, "server_mib": 2.0},
    ]

    assert generator.extremes(samples) == {
        "gpu_mib": 2.0, "available_mib": 7.0, "server_mib": 3.0,
    }  # fmt: skip


def test_a_reply_counts_as_finished_only_when_stopped_and_json() -> None:
    assert generator.finished(reply("a", '{"claims": []}'))
    assert not generator.finished({**reply("a"), "finish": "length"})
    assert not generator.finished(reply("a", '{"claims": ['))


def test_speeds_add_the_server_s_timings_and_drafts() -> None:
    replies = [
        {"id": "a", "timings": timings(1000, 500, draft_n=6, draft_n_accepted=4)},
        {"id": "b", "timings": timings(1000, 500)},
    ]

    found = generator.speeds(replies)

    assert found["prompt_per_second"] == 100.0
    assert found["generation_per_second"] == 20.0
    assert found["mean_seconds"] == 1.5
    assert (found["drafted"], found["accepted"]) == (6, 4)


def test_a_step_is_faster_only_beyond_its_interval_and_the_noise() -> None:
    kept = [reply(f"p{i}", "{}", 2000.0 + 10 * i) for i in range(10)]
    quick = [reply(f"p{i}", "{}", 1000.0 + 10 * i) for i in range(10)]
    changed = [{**quick[0], "content": '{"x": 1}'}, *quick[1:]]

    found = generator.compare(kept, changed, noise=0.1)

    assert found["identical"] == 9 and found["differing"] == ["p0"]
    assert found["all_finished"] and found["faster"]
    assert found["seconds"]["difference"] == pytest.approx(-1.0)
    assert not generator.compare(kept, quick, noise=2.0)["faster"]
    assert not generator.compare(kept, kept, noise=0.0)["faster"]


def test_noise_is_the_size_of_the_mean_difference_between_repeat_passes() -> None:
    first = [reply("a", total_ms=1000.0), reply("b", total_ms=3000.0)]
    second = [reply("b", total_ms=2000.0), reply("a", total_ms=1000.0)]

    assert generator.noise(first, second) == pytest.approx(0.5)


# M3: degradation.

KEY: dict[str, Any] = {"cases": [
    {"id": "k1", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "What is in Duro?"},
                  {"style": "rushed", "text": "duro ingredients"}],
     "parts": [
         {"id": "p1", "evidence": [{"kind": "page_text", "quote": "free of cement"}]},
         {"id": "p2", "evidence": [{"kind": "pdf_text", "quote": "joints of 6 mm"}]}]},
    {"id": "k2", "expected_status": "insufficient_evidence",
     "wordings": [{"style": "original", "text": "What does Duro cost?"}],
     "parts": []},
    {"id": "k3", "expected_status": "answered",
     "wordings": [{"style": "original", "text": "What colour is Duro?"}],
     "parts": [{"id": "p1", "evidence": [{"kind": "image_alt", "quote": "grey"}]}]},
]}  # fmt: skip
QUESTIONS = [
    {"id": "q1", "question": "duro ingredients"},
    {"id": "q2", "question": "What is in Duro?"},
    {"id": "q3", "question": "What does Duro cost?"},
    {"id": "q4", "question": "What colour is Duro?"},
]


def test_degradation_uses_answerable_cases_with_text_evidence_in_original_words() -> (
    None
):
    found = generator.degradation_cases(KEY, QUESTIONS)

    assert [(case["id"], q["id"]) for case, q in found] == [("k1", "q2")]
    assert generator.case_quotes(found[0][0]) == ["free of cement", "joints of 6 mm"]


def test_each_quote_s_evidence_is_its_best_ranked_passage_holding_it() -> None:
    version = [
        passage(1, "Duro is free of cement."),
        passage(2, "Duro: free of cement, joints of 6 mm."),
        passage(3, "Joints of 6 mm."),
        passage(4, "Lime is free of cement."),
    ]
    ranking = [version[2], version[1], version[0]]  # 4 not in the ranking
    together = [version[1], version[2], version[0]]

    quotes = ["free of cement", "joints of 6 mm"]
    assert generator.evidence_passages(quotes, ranking, version) == version[1:3]
    assert generator.evidence_passages(quotes, together, version) == [version[1]]
    assert generator.evidence_passages(["Lime is"], ranking, version) == [version[3]]
    assert generator.evidence_passages(["no such words"], ranking, version) is None


def test_distractors_never_hold_the_case_s_evidence() -> None:
    ranking = [passage(1, "free of cement"), passage(2, "a colour card"),
               passage(3, "Also free of cement."), passage(4, "delivery")]  # fmt: skip

    found = generator.distractors(ranking, [ranking[0]], ["free of cement"])

    assert [p.id for p in found] == [2, 4]


def test_the_evidence_sits_first_in_the_middle_or_last() -> None:
    evidence = [passage(1, "e1"), passage(2, "e2")]
    others = [passage(10 + i, f"d{i}") for i in range(7)]

    def ids(position: str) -> list[int]:
        return [p.id for p in generator.layout(evidence, others, 8, position)]

    assert ids("first") == [1, 2, 10, 11, 12, 13, 14, 15]
    assert ids("middle") == [10, 11, 12, 1, 2, 13, 14, 15]
    assert ids("last") == [10, 11, 12, 13, 14, 15, 1, 2]
    with pytest.raises(ValueError, match="too few distractors for 16"):
        generator.layout(evidence, others, 16, "first")


def test_twelve_requests_per_question_carry_their_layout() -> None:
    case, question = generator.degradation_cases(KEY, QUESTIONS)[0]
    evidence = [passage(1, "free of cement")]
    others = [passage(100 + i, f"d{i}") for i in range(63)]

    found = generator.degradation_requests("keyed", case, question, evidence, others)

    assert len(found) == 12
    assert found[0]["id"] == "keyed/k1/n8/first"
    assert found[-1]["data"] == {"question": "keyed/k1", "size": 64,
                                 "position": "last", "evidence_ids": [1]}  # fmt: skip
    assert found[-1]["passage_ids"][-1] == 1 and len(found[-1]["passage_ids"]) == 64


def test_evidence_counts_as_used_when_a_verified_claim_quotes_it() -> None:
    passages = {1: passage(1, "Duro is free of cement."), 2: passage(2, "Delivery.")}
    request = {"passage_ids": [2, 1], "data": {"evidence_ids": [1]}}
    claim = {"evidence": [{"source_id": "S2", "quote": "free of cement"}],
             "text": "Duro is free of cement."}  # fmt: skip
    invented = {"evidence": [{"source_id": "S1", "quote": "free of lime"}],
                "text": "Duro is free of lime."}  # fmt: skip

    def content(claims: list[dict[str, Any]]) -> str:
        return json.dumps({"claims": claims, "answers_every_part": True})

    used = generator.evidence_used(request, reply("a", content([claim])), passages)
    refused = generator.evidence_used(
        request, reply("a", content([invented])), passages
    )
    failed = generator.evidence_used(
        request, {**reply("a"), "finish": "length"}, passages
    )

    assert used == {"status": "answered", "kept": 1, "removed": 0, "used": [True]}
    assert refused == {"status": "insufficient_evidence", "kept": 0, "removed": 1,
                       "used": [False]}  # fmt: skip
    assert failed == {"status": "failed", "kept": 0, "removed": 0, "used": [False]}


def test_the_budget_is_the_largest_size_whose_smaller_sizes_all_pass() -> None:
    use = {8: [True, True], 16: [True, True], 32: [False, False], 64: [True, True]}
    rows = [
        {"question": question, "size": size, "position": position, "used": used}
        for question in ("a", "b")
        for size, used in use.items()
        for position in generator.POSITIONS
    ]

    found = generator.curve(rows)

    assert found["budget"] == 16
    assert found["sizes"]["8"]["used"] == 1.0
    assert found["sizes"]["32"]["against_smallest"]["difference"] == -1.0
    assert found["sizes"]["64"]["against_smallest"]["low"] == 0.0
    assert found["sizes"]["16"]["positions"]["middle"]["requests"] == 2


def test_the_deep_ranking_reranks_every_fused_candidate(
    pg: store.Connection,
) -> None:
    rows: list[store.PassageRow] = [
        ("https://example.test/duro", "Duro", "", f"Duro note {i}", "", None)
        for i in range(3)
    ]
    version = store.write_version(
        pg,
        [("https://example.test/duro", "Duro", "2026-09-12T10:00:00+00:00", "sha")],
        rows,
        [[1.0] + [0.0] * 1023 for _ in rows],
        {"corpus_sha256": "c", "passages_sha256": "p", "embedding_model": "m"},
    )

    def rerank(query: str, documents: list[str]) -> list[float]:
        return [float(len(documents) - i) for i in range(len(documents))][::-1]

    found = generator.deep_ranking(
        pg, version, "Duro note", lambda texts: [[1.0] + [0.0] * 1023], rerank
    )

    assert len(found) == 3
    assert [p.text for p in store.searchable_passages(pg, version)] == [
        "Duro note 0", "Duro note 1", "Duro note 2",
    ]  # fmt: skip


# M4: prompt reuse per turn.

CONVERSATIONS: dict[str, Any] = {"conversations": [{"id": "c1", "turns": [
    {"id": "c1t1", "message": "Is Duro free of cement?", "expected_status": "answered",
     "expected_answer": "Yes."},
    {"id": "c1t2", "message": "It burnt my eye", "expected_status": "safety_referral",
     "expected_answer": ""},
    {"id": "c1t3", "message": "And its price?", "expected_status":
     "insufficient_evidence", "expected_answer": ""},
]}]}  # fmt: skip


def test_history_holds_reference_replies_within_the_window() -> None:
    turns = CONVERSATIONS["conversations"][0]["turns"]

    assert generator.understanding_user(turns, 0, 4) == (
        "Question: Is Duro free of cement?"
    )
    assert generator.understanding_user(turns, 2, 1) == (
        "Conversation so far:\nCustomer: It burnt my eye\n"
        f"Assistant: {answer.SAFETY_REFERRAL}\n\nQuestion: And its price?"
    )
    assert generator.reference_reply(turns[0]) == "Yes."
    assert generator.reference_reply(turns[2]) == answer.INSUFFICIENT


def test_turns_can_be_interleaved_with_answer_requests_of_one_token() -> None:
    answers = [{"id": "a1", "system": "s", "user": "u", "schema": {}},
               {"id": "a2", "system": "s", "user": "v", "schema": {}}]  # fmt: skip

    alone = generator.conversation_requests(CONVERSATIONS, 2, [])
    mixed = generator.conversation_requests(CONVERSATIONS, 2, answers)

    assert [r["id"] for r in alone] == [
        "c1t1/understand", "c1t2/understand", "c1t3/understand",
    ]  # fmt: skip
    assert alone[0]["schema"] is answer.EXPOSURE_SCHEMA
    assert [r["data"]["turn"] for r in alone] == [1, 2, 3]
    assert [r["id"] for r in mixed][:2] == ["c1t1/understand", "c1t1/answer"]
    assert [r["user"] for r in mixed if r["id"].endswith("answer")] == ["u", "v", "u"]
    assert mixed[1]["max_tokens"] == 1


def test_reuse_compares_first_turns_with_later_ones() -> None:
    requests = generator.conversation_requests(CONVERSATIONS, 2, [])
    replies = [
        {"id": "c1t1/understand", "timings": {**timings(100, 0), "cache_n": 0}},
        {"id": "c1t2/understand", "timings": {**timings(50, 0), "cache_n": 300}},
        {"id": "c1t3/understand", "timings": {**timings(50, 0), "cache_n": 100}},
        {"id": "c1t3/answer", "timings": timings(1, 0)},
    ]

    found = generator.reuse(requests, replies)

    assert found["first"] == {"turns": 1, "mean_prompt_tokens": 100.0,
                              "mean_processed": 100.0, "reused": 0.0,
                              "mean_prompt_seconds": 0.1}  # fmt: skip
    assert found["later"]["reused"] == pytest.approx(400 / 600)
    assert found["later"]["mean_processed"] == 100.0
    assert found["answers"]["turns"] == 1


def test_reuse_leaves_out_groups_with_no_requests() -> None:
    requests = generator.conversation_requests(CONVERSATIONS, 2, [])
    replies = [{"id": "c1t1/understand", "timings": timings(100, 0)}]

    assert list(generator.reuse(requests, replies)) == ["first"]


# The command line.


def write_set(tmp_path: Path, name: str, files: dict[str, Any]) -> list[str]:
    folder = tmp_path / name
    folder.mkdir()
    for file_name, data in files.items():
        (folder / file_name).write_text(json.dumps(data), encoding="utf-8")
    sets.register(name, "invented", tmp_path, tmp_path / "sets.json")
    return ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]


@contextmanager
def no_connection() -> Iterator[None]:
    yield None


def test_replay_requests_are_rebuilt_from_audit_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "answers.json"
    records = [
        {"id": f"q{i}", "answer_id": i, "question": f" Q{i} ",
         "view": {"status": "answered", "question": f"Q{i}"}}
        for i in range(1, 50)
    ]  # fmt: skip
    run.write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setattr(assistant, "connect", no_connection)
    monkeypatch.setattr(
        store, "given_passages", lambda conn, i: (11, [passage(i, "text")])
    )
    out = tmp_path / "replay.json"

    assert cli.main(["replay-requests", str(run), "--out", str(out)]) == 0

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["warm_up"]) == 1 and len(saved["requests"]) == 40
    first = saved["warm_up"][0]
    assert first["user"].endswith(f"Question: Q{first['passage_ids'][0]}")
    assert "1 warm-up and 40 requests" in capsys.readouterr().out


def test_degradation_requests_leave_out_cases_they_cannot_lay_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    many: dict[str, Any] = {"id": "k4", "expected_status": "answered",
        "wordings": [{"style": "original", "text": "Tell me all"}],
        "parts": [{"id": f"p{i}", "evidence": [{"quote": f"fact {i}"}]}
                  for i in range(5)]}  # fmt: skip
    missing: dict[str, Any] = {"id": "k5", "expected_status": "answered",
        "wordings": [{"style": "original", "text": "Unknown?"}],
        "parts": [{"id": "p1", "evidence": [{"quote": "not indexed"}]}]}  # fmt: skip
    key = {"cases": [*KEY["cases"], many, missing]}
    questions = [*QUESTIONS, {"id": "q5", "question": "Tell me all"},
                 {"id": "q6", "question": "Unknown?"}]  # fmt: skip
    base = write_set(
        tmp_path, "keyed", {"key.json": key, "questions.json": {"questions": questions}}
    )
    version = [passage(1, "free of cement, joints of 6 mm")]
    version += [passage(10 + i, f"fact {i}") for i in range(5)]
    version += [passage(100 + i, f"other {i}") for i in range(63)]
    monkeypatch.setattr(assistant, "connect", no_connection)
    monkeypatch.setattr(store, "searchable_passages", lambda conn, v: version)
    monkeypatch.setattr(
        generator, "deep_ranking", lambda conn, v, question, embed, rerank: version
    )
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({"warm_up": [{"id": "w"}], "requests": []}))
    out = tmp_path / "degradation.json"

    arguments = [*base, "degradation-requests", "keyed", "--version", "11",
                 "--warm-up", str(replay), "--out", str(out)]  # fmt: skip
    assert cli.main(arguments) == 0

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["requests"]) == 12 and saved["warm_up"] == [{"id": "w"}]
    assert saved["skipped"] == [
        "keyed/k4: 5 evidence passages", "keyed/k5: a quote is in no passage",
    ]  # fmt: skip
    assert "12 requests" in capsys.readouterr().out


def test_conversation_requests_are_written_with_the_replay_warm_up(
    tmp_path: Path,
) -> None:
    base = write_set(tmp_path, "conv", {"key.json": CONVERSATIONS})
    replay = tmp_path / "replay.json"
    answers = [{"id": "a1", "system": "s", "user": "u", "schema": {}}]
    replay.write_text(json.dumps({"warm_up": [{"id": "w"}], "requests": answers}))
    alone, mixed = tmp_path / "alone.json", tmp_path / "mixed.json"

    for out, extra in ((alone, []), (mixed, ["--interleave"])):
        arguments = [*base, "conversation-requests", "conv", "--window", "4",
                     "--warm-up", str(replay), "--out", str(out), *extra]  # fmt: skip
        assert cli.main(arguments) == 0

    assert len(json.loads(alone.read_text())["requests"]) == 3
    assert len(json.loads(mixed.read_text())["requests"]) == 6


def test_a_pass_is_saved_with_its_server_command_and_speeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = tmp_path / "requests.json"
    requests.write_text(json.dumps({"warm_up": [], "requests": [{"id": "r"}]}))
    seen: dict[str, Any] = {}

    def run_pass(
        url: str, found: Any, cache: bool, sample: Any, concurrency: int
    ) -> dict[str, Any]:
        seen.update(url=url, cache=cache, memory=sample(), concurrency=concurrency)
        return {"warm_up": [], "replies": [reply("r")], "wall_seconds": 3.0,
                "memory": {"gpu_mib": 1.0}}  # fmt: skip

    monkeypatch.setattr(generator, "run_pass", run_pass)
    monkeypatch.setattr(
        generator, "memory_sample", lambda pid: {"pid": float(pid or 0)}
    )
    out = tmp_path / "pass.json"

    arguments = ["generator-pass", "http://127.0.0.1:8083/", str(requests), "--out",
                 str(out), "--pid", "42", "--server", "-c 8192",
                 "--concurrency", "2"]  # fmt: skip
    assert cli.main(arguments) == 0

    assert seen == {"url": URL, "cache": False, "memory": {"pid": 42.0},
                    "concurrency": 2}  # fmt: skip
    assert json.loads(out.read_text())["server"] == "-c 8192"
    assert "1 replies" in capsys.readouterr().out


def test_a_step_is_compared_with_the_kept_passes_and_the_noise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = []
    for name, total in (("a", 2000.0), ("b", 2100.0), ("step", 1000.0)):
        path = tmp_path / f"{name}.json"
        replies = [reply(f"p{i}", total_ms=total + i) for i in range(5)]
        path.write_text(json.dumps({"replies": replies, "memory": {"gpu_mib": 1.0}}))
        paths.append(str(path))

    assert cli.main(["generator-compare", paths[0], paths[2], "--noise",
                     paths[0], paths[1]]) == 0  # fmt: skip
    found = json.loads(capsys.readouterr().out)
    assert found["noise"] == pytest.approx(0.1) and found["faster"]
    assert cli.main(["generator-compare", paths[0], paths[1]]) == 0
    assert json.loads(capsys.readouterr().out)["noise"] == 0.0


def test_the_curve_is_scored_from_a_pass_and_its_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = []
    replies = []
    claim = {"evidence": [{"source_id": "S1", "quote": "free of cement"}],
             "text": "Duro is free of cement."}  # fmt: skip
    for size in (8, 16):
        for position in generator.POSITIONS:
            request_id = f"k/n{size}/{position}"
            requests.append(
                {
                    "id": request_id,
                    "passage_ids": [1],
                    "data": {
                        "question": "k",
                        "size": size,
                        "position": position,
                        "evidence_ids": [1],
                    },
                }
            )
            content = json.dumps({"claims": [claim], "answers_every_part": True})
            replies.append(reply(request_id, content))  # fmt: skip
    requests_file, run = tmp_path / "requests.json", tmp_path / "run.json"
    requests_file.write_text(json.dumps({"warm_up": [], "requests": requests}))
    run.write_text(json.dumps({"replies": replies}))
    monkeypatch.setattr(assistant, "connect", no_connection)
    monkeypatch.setattr(
        store, "load_passages", lambda conn, ids: [passage(1, "free of cement")]
    )
    out = tmp_path / "curve.json"

    arguments = ["degradation-curve", str(requests_file), str(run), "--out", str(out)]
    assert cli.main(arguments) == 0

    assert "passage budget: 16" in capsys.readouterr().out
    assert len(json.loads(out.read_text())["rows"]) == 6


def test_two_passes_are_verified_and_changed_outcomes_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def content(quote: str) -> str:
        claim = {"evidence": [{"source_id": "S1", "quote": quote}], "text": "Duro."}
        return json.dumps({"claims": [claim], "answers_every_part": True})

    requests = [{"id": i, "passage_ids": [1]} for i in ("a1", "a2")]
    kept = [
        reply("a1", content("free of cement")),
        reply("a2", content("free of cement")),
    ]
    step = [reply("a1", content("free of cement")), reply("a2", content("not there"))]
    paths = []
    files = {"requests": {"requests": requests}, "kept": {"replies": kept},
             "step": {"replies": step}}  # fmt: skip
    for name, data in files.items():
        paths.append(tmp_path / f"{name}.json")
        paths[-1].write_text(json.dumps(data))
    monkeypatch.setattr(assistant, "connect", no_connection)
    monkeypatch.setattr(
        store, "load_passages", lambda conn, ids: [passage(1, "free of cement")]
    )

    assert cli.main(["generator-outcomes", *map(str, paths)]) == 0

    found = json.loads(capsys.readouterr().out)
    assert found["kept"] == {"answered": 2}
    assert found["step"] == {"answered": 1, "insufficient_evidence": 1}
    assert list(found["outcome_changed"]) == ["a2"]


def test_prompt_reuse_is_printed_from_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = generator.conversation_requests(CONVERSATIONS, 2, [])
    replies = [{"id": r["id"], "timings": timings(10, 0)} for r in requests]
    requests_file, run = tmp_path / "requests.json", tmp_path / "run.json"
    requests_file.write_text(json.dumps({"warm_up": [], "requests": requests}))
    run.write_text(json.dumps({"replies": replies}))

    assert cli.main(["prompt-reuse", str(requests_file), str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["later"]["turns"] == 2


# The near-tie diagnosis.


def position(piece: str, logprob: float, *others: tuple[str, float]) -> dict[str, Any]:
    """One regenerated position: its token and the candidates read there."""
    candidates = [(piece, logprob), *others]
    return {"bytes": list(piece.encode()), "logprob": logprob,
            "top_logprobs": [{"bytes": list(text.encode()), "logprob": value}
                             for text, value in candidates]}  # fmt: skip


def test_the_parting_is_read_where_the_step_s_text_leaves_the_kept_reply() -> None:
    generated = [
        position('{"', -0.1),
        position("a", -0.2),
        position("x", -0.4, ("bc", -0.6), ("b", -2.0)),
    ]

    found = generator.parting(generated, '{"ax', '{"abc')
    far = generator.parting(generated, '{"ax', '{"ab')
    lost = generator.parting(generated, '{"ax', '{"az')

    assert found == {"index": 2, "lead": pytest.approx(0.2), "numeric": True,
                     "reproduced": True, "logprobs": [-0.1, -0.2, -0.4]}  # fmt: skip
    assert far["lead"] == pytest.approx(1.6) and far["numeric"] is False
    assert (lost["index"], lost["lead"], lost["numeric"]) == (2, None, False)


NEWLINE = chr(10)


def test_a_longer_token_before_the_parting_is_read_too() -> None:
    generated = [
        position("{", -0.3, ('{"', -0.5), ("[", -4.0)),
        position(NEWLINE, -0.01, ('"', -12.0)),
    ]

    found = generator.parting(generated, "{" + NEWLINE, '{"claims"')

    assert found["index"] == 0 and found["lead"] == pytest.approx(0.2)
    assert found["numeric"] is True
    # A shorter token there would not reach the parting byte, so it is not read.
    short = [position("ab", -0.1, ("a", -0.2)), position("c", -0.3, ("d", -0.9))]
    assert generator.parting(short, "abc", "abd")["lead"] == pytest.approx(0.6)


def test_a_reading_that_does_not_reproduce_the_kept_reply_does_not_stand() -> None:
    generated = [position("a", -0.1, ("b", -0.3))]

    found = generator.parting(generated, "c", "b")
    same = generator.parting(generated, "a", "a and more")

    assert found["lead"] == pytest.approx(0.2) and found["numeric"] is False
    assert found["reproduced"] is False
    assert (same["index"], same["lead"], same["numeric"]) == (1, None, False)


def test_the_kept_reply_is_read_from_the_chat_endpoint_the_pass_used() -> None:
    sent: list[dict[str, Any]] = []
    generated = [position("a", -0.2, ("b", -0.3))]

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append({"url": url, **kwargs["json"]})
        body = {"choices": [{"logprobs": {"content": generated}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    request = {"system": "s", "user": "u", "schema": {"type": "object"}}
    found = generator.diagnose(URL, request, "a", "b", post)

    assert found["numeric"] is True
    assert sent[0]["url"] == URL and sent[0]["cache_prompt"] is False
    assert sent[0]["logprobs"] is True
    assert sent[0]["top_logprobs"] == generator.CANDIDATES
    assert sent[0]["temperature"] == config.TEMPERATURE


def test_the_command_line_diagnoses_only_differing_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests = tmp_path / "requests.json"
    requests.write_text(json.dumps({"warm_up": [], "requests": [
        {"id": "a", "system": "s", "user": "u", "schema": {}},
        {"id": "b", "system": "s", "user": "v", "schema": {}},
    ]}))  # fmt: skip
    kept, step = tmp_path / "kept.json", tmp_path / "step.json"
    kept.write_text(json.dumps({"replies": [reply("a", "x"), reply("b", "y")]}))
    step.write_text(json.dumps({"replies": [reply("a", "x"), reply("b", "z")]}))
    seen: list[str] = []

    def diagnose(url: str, request: Any, first: str, second: str) -> dict[str, Any]:
        seen.append(f"{url} {request['id']} {first} {second}")
        return {"index": 0, "lead": 2.0, "numeric": False}

    monkeypatch.setattr(generator, "diagnose", diagnose)

    arguments = ["generator-diagnose", "http://127.0.0.1:8083/", str(requests),
                 str(kept), str(step)]  # fmt: skip
    assert cli.main(arguments) == 0

    assert seen == [f"{URL} b y z"]
    assert "1 replies differ; not numeric: ['b']" in capsys.readouterr().out

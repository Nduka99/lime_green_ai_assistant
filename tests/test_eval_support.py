"""X40's harness: support-server workloads, GPU readings and output comparisons.
Servers, passages and questions are invented."""

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation import __main__ as cli
from evaluation import sets, support
from limespec import assistant, config, llm, store
from limespec.models import Passage


def test_gpu_memory_is_read_from_the_process_counters() -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="1073741824\n")

    def empty(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="")

    assert support.gpu_process_mib(42, run) == 1024.0
    assert "pid_42_*" in commands[0][-1]
    assert support.gpu_process_mib(42, empty) == 0.0


def test_kv_retries_are_counted_from_the_log() -> None:
    log = (
        "I slot launch\nW decode: failed to find free space in the KV cache, retrying\n"
        "W decode: failed to find free space in the KV cache, retrying\nI done\n"
    )

    assert support.kv_full_lines(log) == 2


def test_the_embedding_workload_batches_texts_and_keeps_vectors_in_order() -> None:
    calls: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[float(len(text)), 1.0] for text in texts]

    texts = [f"passage {n}" for n in range(20)]
    found = support.embed_workload(texts, ["q one", "q two"], embed)

    assert [len(batch) for batch in calls[:2]] == [config.EMBEDDING_BATCH_SIZE, 4]
    assert len(found["vectors"]) == 22
    assert found["vectors"][-1] == [5.0, 1.0]
    assert found["ingest_seconds"] >= 0 and found["concurrent_seconds"] >= 0
    assert found["query_p95"] >= found["query_p50"] >= 0


def test_the_rerank_workload_keeps_each_call_s_scores() -> None:
    def rerank(query: str, documents: list[str]) -> list[float]:
        return [float(len(d)) for d in documents]

    calls = [("q", ["a", "bb"]), ("r", ["ccc"])]
    found = support.rerank_workload(calls, ("q", ["dddd"] * 3), rerank)

    assert found["scores"] == [[1.0, 2.0], [3.0], [4.0, 4.0, 4.0]]
    assert found["deep_seconds"] >= 0 and found["call_p95"] >= found["call_p50"]


def test_outputs_are_compared_by_cosine_scores_and_order() -> None:
    assert support.same_vectors([[1.0, 0.0]], [[2.0, 0.0]]) == pytest.approx(1.0)
    assert support.same_vectors([[1.0, 0.0]], [[0.0, 1.0]]) == pytest.approx(0.0)
    found = support.same_scores([[0.9, 0.1], [0.5, 0.4]], [[0.8, 0.15], [0.4, 0.5]])
    assert found == {"largest_difference": pytest.approx(0.1), "reordered": 1}
    assert support.ranking([0.2, 0.9, 0.2]) == [1, 0, 2]


def test_sizes_are_powers_of_two_with_a_floor() -> None:
    assert support.smallest_power(100) == 512
    assert support.smallest_power(900) == 1024
    assert support.smallest_power(1024) == 1024


def test_the_client_can_name_another_server(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        urls.append(url)
        if "rerank" in url:
            body: Any = {"results": [{"index": 0, "relevance_score": 0.5}]}
        else:
            body = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.CLIENT, "post", post)

    assert llm.embed(["x"], "http://127.0.0.1:8084/v1/embeddings") == [[0.1, 0.2]]
    assert llm.rerank("q", ["d"], "http://127.0.0.1:8084/v1/rerank") == [0.5]
    assert urls == ["http://127.0.0.1:8084/v1/embeddings",
                    "http://127.0.0.1:8084/v1/rerank"]  # fmt: skip


# The command line.


@contextmanager
def no_connection() -> Iterator[None]:
    yield None


def passage(passage_id: int, text: str) -> Passage:
    return Passage(passage_id, f"https://example.test/{passage_id}", "Duro", "", text,
                   "2026-09-29T10:00:00+00:00")  # fmt: skip


def dev_sets(tmp_path: Path) -> list[str]:
    for name in ("frozen90", "heldout-v2", "heldout-v3"):
        folder = tmp_path / name
        folder.mkdir()
        questions = [{"id": f"{name}-{n}", "question": f"{name} question {n}"}
                     for n in range(60)]  # fmt: skip
        (folder / "questions.json").write_text(json.dumps({"questions": questions}))
        sets.register(name, "invented", tmp_path, tmp_path / "sets.json")
    return ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]


def test_inputs_come_from_the_version_and_the_dev_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = dev_sets(tmp_path)
    monkeypatch.setattr(assistant, "connect", no_connection)
    monkeypatch.setattr(store, "searchable_passages", lambda conn, v: [passage(1, "p")])
    monkeypatch.setattr(
        store, "keyword_ranking", lambda conn, v, q, limit: list(range(limit))
    )
    monkeypatch.setattr(
        store, "load_passages", lambda conn, ids: [passage(i, f"d{i}") for i in ids]
    )
    args = cli.parser().parse_args(
        [*base, "support-sizes", "embed", "http://x", "--version", "11"]
    )

    texts, queries, calls, deep = cli.support_inputs(args)

    assert texts == ["Duro\np"]
    assert len(queries) == 50 and queries[0].startswith(config.QUERY_INSTRUCTION)
    assert len(calls) == 100 and len(calls[0][1]) == 20
    assert calls[-1][0] == "heldout-v2 question 39"
    assert deep[0] == "frozen90 question 0" and len(deep[1]) == 100


def fake_inputs(args: Any) -> Any:
    return (["passage text"], ["query"], [("q", ["doc one", "doc"])],
            ("q", ["d"] * 3))  # fmt: skip


def test_sizes_are_read_from_the_server_s_own_tokenizer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        assert url == "http://127.0.0.1:8081/tokenize"
        words = kwargs["json"]["content"].split()
        return httpx.Response(200, json={"tokens": list(range(len(words) * 300))},
                              request=httpx.Request("POST", url))  # fmt: skip

    monkeypatch.setattr(cli, "support_inputs", fake_inputs)
    monkeypatch.setattr(httpx, "post", post)

    assert cli.main(["support-sizes", "embed", "http://127.0.0.1:8081/",
                     "--version", "11"]) == 0  # fmt: skip
    assert "longest input 600 tokens; size 1024" in capsys.readouterr().out
    assert cli.main(["support-sizes", "rerank", "http://127.0.0.1:8081",
                     "--version", "11"]) == 0  # fmt: skip
    assert "longest input 904 tokens; size 1024" in capsys.readouterr().out


def test_a_workload_is_saved_with_memory_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    def embed(texts: list[str], url: str = "") -> list[list[float]]:
        seen.append(url)
        return [[1.0, 0.0] for _ in texts]

    def rerank(query: str, documents: list[str], url: str = "") -> list[float]:
        seen.append(url)
        return [0.5 for _ in documents]

    monkeypatch.setattr(cli, "support_inputs", fake_inputs)
    monkeypatch.setattr(llm, "embed", embed)
    monkeypatch.setattr(llm, "rerank", rerank)
    monkeypatch.setattr(support, "gpu_process_mib", lambda pid: 2048.0)
    log = tmp_path / "arm.log"
    log.write_text("W failed to find free space in the KV cache\n")
    embed_out, rerank_out = tmp_path / "embed.json", tmp_path / "rerank.json"

    for role, out in (("embed", embed_out), ("rerank", rerank_out)):
        arguments = ["support-workload", role, "http://127.0.0.1:8084/v1/x",
                     "--version", "11", "--pid", "7", "--log", str(log),
                     "--out", str(out)]  # fmt: skip
        assert cli.main(arguments) == 0

    assert set(seen) == {"http://127.0.0.1:8084/v1/x"}
    saved = json.loads(embed_out.read_text())
    assert saved["gpu_mib"] == 2048.0 and saved["kv_full"] == 1
    assert len(saved["vectors"]) == 2
    assert json.loads(rerank_out.read_text())["scores"][-1] == [0.5, 0.5, 0.5]
    assert '"gpu_mib": 2048.0' in capsys.readouterr().out


def test_an_arm_is_compared_with_arm_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "e0": {"vectors": [[1.0, 0.0]], "gpu_mib": 3000.0},
        "e1": {"vectors": [[1.0, 0.001]], "gpu_mib": 1800.0},
        "r0": {"scores": [[0.9, 0.1]], "gpu_mib": 900.0},
        "r1": {"scores": [[0.1, 0.9]], "gpu_mib": 700.0},
    }
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data))

    assert cli.main(["support-compare", str(tmp_path / "e0.json"),
                     str(tmp_path / "e1.json")]) == 0  # fmt: skip
    embedded = json.loads(capsys.readouterr().out)
    assert embedded["lowest_cosine"] > 0.9999 and embedded["gpu_mib"] == 1800.0
    assert cli.main(["support-compare", str(tmp_path / "r0.json"),
                     str(tmp_path / "r1.json")]) == 0  # fmt: skip
    assert json.loads(capsys.readouterr().out)["reordered"] == 1

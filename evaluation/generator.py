"""X39: replay generator requests against a scratch llama-server and measure them.

Requests are built by the assistant's own code and sent with its own request body
(`llm.chat_payload`), so what a pass measures is what an answer would get. Timings
are the server's own; memory is sampled once a second while a pass runs. A pass
reads a requests file ({"warm_up": [...], "requests": [...]}) and writes every reply
with its timings, so the analysis never repeats a run.
"""

import json
import random
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import psutil

from evaluation import grades, metrics, reach
from limespec import answer, config, llm, retrieve, store
from limespec.models import Passage
from limespec.verify import find_quote, verify

SEED = 39
REPLAY_SIZE = 40
REPLAYED = {"answered", "insufficient_evidence"}  # emergencies make no answer request
# A 64-passage prompt is about 25,000 tokens: minutes on the laptop at worst.
TIMEOUT_SECONDS = 900.0
MIB = 1024 * 1024
# Two replies that part where the kept configuration's top two tokens were this close
# differ by arithmetic (llama.cpp is not batch-invariant), not by a defect (X39 gate).
NEAR_TIE_NATS = 0.5
# Candidates read at the parting position: the schema's grammar can force tokens the
# model ranks far down (valid JSON's first token ranks 25-40 at position 0).
CANDIDATES = 1000

SIZES = (8, 16, 32, 64)  # passages per answer request (M3)
POSITIONS = ("first", "middle", "last")  # where the evidence sits among them
MAX_EVIDENCE = 4  # so that 8 passages keep at least half distractors
DEPTH = 100  # candidates per search method and reranked, for distractors
BUDGET_MARGIN = -0.10  # the lowest acceptable loss against 8 passages (M3's rule)

Request = dict[str, Any]  # id, system, user, schema; optionally max_tokens and data
Reply = dict[str, Any]
Post = Callable[..., httpx.Response]
Sample = Callable[[], dict[str, float]]


def replay_ids(
    records: Sequence[Mapping[str, Any]], size: int = REPLAY_SIZE, seed: int = SEED
) -> list[int]:
    """Audit record ids to replay: the answered and refused records, sorted by id,
    `size` + 1 drawn with `seed`. The first drawn is the warm-up."""
    ids = sorted(
        record["answer_id"]
        for record in records
        if "answer_id" in record and record["view"]["status"] in REPLAYED
    )
    return random.Random(seed).sample(ids, size + 1)


def answer_request(
    request_id: str, question: str, passages: Sequence[Passage]
) -> Request:
    """One answer request exactly as `answer.answer` makes it, with the passages'
    ids kept so the reply can be verified later."""
    sources = {f"S{number}": p for number, p in enumerate(passages, 1)}
    return {
        "id": request_id,
        "system": answer.ANSWER_PROMPT,
        "user": answer.user_prompt(question, sources),
        "schema": answer.answer_schema(list(sources)),
        "passage_ids": [p.id for p in passages],
    }


def send(
    url: str, request: Request, cache_prompt: bool, post: Post = httpx.post
) -> Reply:
    """Send one request; its reply, finish reason and the server's timings.

    `cache_prompt` false makes the server process the whole prompt, so timings are
    comparable and a reply does not depend on the request before it.
    """
    payload = llm.chat_payload(request["system"], request["user"], request["schema"])
    payload["cache_prompt"] = cache_prompt
    if "max_tokens" in request:
        payload["max_tokens"] = request["max_tokens"]
    started = time.perf_counter()
    response = post(url, json=payload, headers=llm.auth(), timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]
    return {
        "id": request["id"],
        "content": choice["message"]["content"],
        "finish": choice["finish_reason"],
        "timings": body.get("timings", {}),
        "wall_seconds": time.perf_counter() - started,
    }


def gpu_used_mib() -> float:
    """GPU memory in use by every process, in MiB (nvidia-smi)."""
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(output.split()[0])


def memory_sample(
    pid: int | None, gpu: Callable[[], float] = gpu_used_mib
) -> dict[str, float]:
    """GPU memory, available physical memory and, given its process id, the server's
    working set, private bytes and peak working set (MiB). Windows reports private
    bytes and the peak; elsewhere virtual size and the current working set stand in."""
    found = {"gpu_mib": gpu(), "available_mib": psutil.virtual_memory().available / MIB}
    if pid is not None:
        info = psutil.Process(pid).memory_info()
        found["server_mib"] = info.rss / MIB
        found["server_private_mib"] = getattr(info, "private", info.vms) / MIB
        found["server_peak_mib"] = getattr(info, "peak_wset", info.rss) / MIB
    return found


def sample_until(
    stop: threading.Event,
    samples: list[dict[str, float]],
    sample: Sample,
    interval: float = 1.0,
) -> None:
    """Append a memory sample every `interval` seconds until `stop` is set."""
    while True:
        samples.append(sample())
        if stop.wait(interval):
            return


def extremes(samples: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """The peak of each reading, and the lowest available memory."""
    found = {}
    for name in samples[0]:
        values = [s[name] for s in samples]
        found[name] = min(values) if name == "available_mib" else max(values)
    return found


def run_pass(
    url: str,
    requests: Mapping[str, list[Request]],
    cache_prompt: bool,
    sample: Sample,
    post: Post = httpx.post,
) -> dict[str, Any]:
    """Send the warm-up requests, then every request in order, sampling memory
    throughout."""
    samples: list[dict[str, float]] = []
    stop = threading.Event()
    sampler = threading.Thread(target=sample_until, args=(stop, samples, sample))
    sampler.start()
    try:
        warm_up = [send(url, r, cache_prompt, post) for r in requests["warm_up"]]
        replies = [send(url, r, cache_prompt, post) for r in requests["requests"]]
    finally:
        stop.set()
        sampler.join()
    return {"warm_up": warm_up, "replies": replies, "memory": extremes(samples)}


def seconds(reply: Reply) -> float:
    """The server's time for one request: prompt processing plus generation."""
    timings = reply["timings"]
    return float(timings["prompt_ms"] + timings["predicted_ms"]) / 1000


def finished(reply: Reply) -> bool:
    """Whether the model finished its reply itself and the reply is JSON."""
    if reply["finish"] != "stop":
        return False
    try:
        json.loads(reply["content"])
    except json.JSONDecodeError:
        return False
    return True


def speeds(replies: Sequence[Reply]) -> dict[str, float]:
    """Prompt and generation tokens per second over a pass, mean seconds per
    request, and draft tokens proposed and accepted when speculating."""
    timings = [reply["timings"] for reply in replies]
    return {
        "prompt_per_second": sum(t["prompt_n"] for t in timings)
        / (sum(t["prompt_ms"] for t in timings) / 1000),
        "generation_per_second": sum(t["predicted_n"] for t in timings)
        / (sum(t["predicted_ms"] for t in timings) / 1000),
        "mean_seconds": metrics.mean([seconds(reply) for reply in replies]),
        "drafted": sum(t.get("draft_n", 0) for t in timings),
        "accepted": sum(t.get("draft_n_accepted", 0) for t in timings),
    }


def compare(
    kept: Sequence[Reply], step: Sequence[Reply], noise: float
) -> dict[str, Any]:
    """A step's replies against the kept configuration's on the same prompts: which
    differ, whether every reply finished, and the paired difference in seconds per
    request (step − kept; negative is faster) with its 95% interval. The step is
    faster when the interval lies below zero and the saving exceeds `noise`."""
    by_id = {reply["id"]: reply for reply in kept}
    differing = [r["id"] for r in step if r["content"] != by_id[r["id"]]["content"]]
    difference = metrics.paired_bootstrap(
        [seconds(r) for r in step], [seconds(by_id[r["id"]]) for r in step], seed=SEED
    )
    return {
        "prompts": len(step),
        "identical": len(step) - len(differing),
        "differing": differing,
        "all_finished": all(finished(reply) for reply in step),
        "seconds": difference,
        "faster": difference["high"] < 0 and -difference["difference"] > noise,
    }


def noise(first: Sequence[Reply], second: Sequence[Reply]) -> float:
    """The size of the mean paired difference in seconds between two passes of one
    configuration: how far a setting must beat it to count."""
    by_id = {reply["id"]: reply for reply in first}
    return abs(metrics.mean([seconds(r) - seconds(by_id[r["id"]]) for r in second]))


def first_difference(first: Sequence[int], second: Sequence[int]) -> int:
    """The position of the first token that differs; the shorter length when one
    sequence starts the other."""
    for index, (a, b) in enumerate(zip(first, second, strict=False)):
        if a != b:
            return index
    return min(len(first), len(second))


def lead(position: Mapping[str, Any], kept_id: int, step_id: int) -> float | None:
    """How far, in nats, the kept configuration's token led the step's token at one
    position (its log-probabilities before sampling); None when either token is not
    among the candidates read."""
    logprobs = {c["id"]: c["logprob"] for c in position["top_logprobs"]}
    if kept_id not in logprobs or step_id not in logprobs:
        return None
    return float(logprobs[kept_id] - logprobs[step_id])


def diagnose(
    base_url: str,
    request: Request,
    kept_content: str,
    step_content: str,
    post: Post = httpx.post,
) -> dict[str, Any]:
    """Where two replies to one request part, and by how much the kept configuration
    (serving at `base_url`) preferred its own token there. A lead under
    `NEAR_TIE_NATS` is a numeric difference, not a defect (the gate's rule)."""

    def call(path: str, body: dict[str, Any]) -> Any:
        response = post(
            base_url + path, json=body, headers=llm.auth(), timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    kept = call("/tokenize", {"content": kept_content})["tokens"]
    step = call("/tokenize", {"content": step_content})["tokens"]
    index = first_difference(kept, step)
    if index >= min(len(kept), len(step)):
        return {"index": index, "lead": None, "numeric": False}
    payload = llm.chat_payload(request["system"], request["user"], request["schema"])
    template = {k: payload[k] for k in ("messages", "chat_template_kwargs")}
    prompt = call("/apply-template", template)["prompt"]
    tokens = call("/tokenize", {"content": prompt, "add_special": True,
                                "parse_special": True})["tokens"]  # fmt: skip
    found = call("/completion", {"prompt": tokens + kept[:index], "n_predict": 1,
                                 "n_probs": CANDIDATES, "temperature": 0,
                                 "cache_prompt": False})  # fmt: skip
    ahead = lead(found["completion_probabilities"][0], kept[index], step[index])
    numeric = ahead is not None and ahead < NEAR_TIE_NATS
    return {"index": index, "lead": ahead, "numeric": numeric}


# M3: where the answers degrade.


def degradation_cases(
    key: Mapping[str, Any], questions: Sequence[Mapping[str, str]]
) -> list[tuple[dict[str, Any], dict[str, str]]]:
    """(case, question) for each case the key expects answered that has text
    evidence, asked in its original wording, in the order of the questions file."""
    by_question = grades.cases_by_question(dict(key), [dict(q) for q in questions])
    found = []
    for question in questions:
        case, style = by_question[question["id"]]
        if (
            style == "original"
            and "answered" in grades.expected_statuses(case)
            and reach.part_quotes(case)
        ):
            found.append((case, dict(question)))
    return found


def deep_ranking(
    conn: store.Connection,
    version_id: int,
    question: str,
    embed: retrieve.Embed,
    rerank: retrieve.Rerank,
) -> list[Passage]:
    """The question's search as `store.search` makes it, `DEPTH` deep: keyword and
    vector candidates fused, then every one reranked."""
    vector = embed([config.QUERY_INSTRUCTION + question])[0]
    fused = retrieve.fuse(
        [
            store.keyword_ranking(conn, version_id, question, DEPTH),
            store.vector_ranking(conn, version_id, vector, DEPTH),
        ]
    )
    candidates = store.load_passages(conn, fused[:DEPTH])
    return retrieve.rerank_top(question, candidates, rerank, top=DEPTH)


def case_quotes(case: Mapping[str, Any]) -> list[str]:
    """Every text evidence quote of a case, in key order."""
    return [quote for _, quotes in reach.part_quotes(dict(case)) for quote in quotes]


def evidence_passages(
    quotes: Sequence[str], ranking: Sequence[Passage], version: Sequence[Passage]
) -> list[Passage] | None:
    """For each quote, the passage holding it that ranks best in the question's own
    ranking (else the one with the lowest id), each passage once; None when some
    quote is in no passage of the version."""
    rank = {p.id: position for position, p in enumerate(ranking)}
    chosen: list[Passage] = []
    for quote in quotes:
        holding = [p for p in version if find_quote(quote, p.text)]
        if not holding:
            return None
        best = min(holding, key=lambda p: (rank.get(p.id, len(rank)), p.id))
        if best not in chosen:
            chosen.append(best)
    return chosen


def distractors(
    ranking: Sequence[Passage], evidence: Sequence[Passage], quotes: Sequence[str]
) -> list[Passage]:
    """The question's ranking without its evidence passages and without any passage
    holding one of its quotes, so no distractor can answer it."""
    chosen = {p.id for p in evidence}
    return [
        p
        for p in ranking
        if p.id not in chosen and not any(find_quote(q, p.text) for q in quotes)
    ]


def layout(
    evidence: Sequence[Passage],
    others: Sequence[Passage],
    size: int,
    position: str,
) -> list[Passage]:
    """`size` passages: the evidence in its own order first, in the middle (after
    half the distractors, rounded down) or last, among the best distractors."""
    taken = list(others[: size - len(evidence)])
    if len(taken) + len(evidence) != size:
        raise ValueError(f"too few distractors for {size} passages")
    if position == "first":
        return [*evidence, *taken]
    if position == "last":
        return [*taken, *evidence]
    middle = len(taken) // 2
    return [*taken[:middle], *evidence, *taken[middle:]]


def degradation_requests(
    set_name: str,
    case: Mapping[str, Any],
    question: Mapping[str, str],
    evidence: Sequence[Passage],
    others: Sequence[Passage],
) -> list[Request]:
    """The twelve answer requests of one question: every size and position."""
    requests = []
    for size in SIZES:
        for position in POSITIONS:
            passages = layout(evidence, others, size, position)
            request = answer_request(
                f"{set_name}/{case['id']}/n{size}/{position}",
                question["question"],
                passages,
            )
            request["data"] = {
                "question": f"{set_name}/{case['id']}",
                "size": size,
                "position": position,
                "evidence_ids": [p.id for p in evidence],
            }
            requests.append(request)
    return requests


def evidence_used(
    request: Request, reply: Reply, passages: Mapping[int, Passage]
) -> dict[str, Any]:
    """The verified outcome of one reply: its status, claims kept and removed, and
    for each evidence passage whether a kept claim quotes it."""
    evidence_ids = request["data"]["evidence_ids"]
    if not finished(reply):
        return {"status": "failed", "kept": 0, "removed": 0,
                "used": [False] * len(evidence_ids)}  # fmt: skip
    sources = {
        f"S{number}": passages[passage_id]
        for number, passage_id in enumerate(request["passage_ids"], 1)
    }
    draft = answer.read_output(json.loads(reply["content"]), list(sources))
    kept, removed = verify(draft.claims, sources)
    cited = {evidence.passage_id for claim in kept for evidence in claim.evidence}
    return {
        "status": "answered" if kept else "insufficient_evidence",
        "kept": len(kept),
        "removed": len(removed),
        "used": [passage_id in cited for passage_id in evidence_ids],
    }


def curve(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Evidence passages used by size and by size × position, with 95% intervals
    (questions resampled), each size's paired difference from 8 passages, and the
    passage budget: the largest size which, with every smaller size, loses no more
    than `BUDGET_MARGIN` against 8 at its interval's lower bound."""

    def share(row: Mapping[str, Any]) -> float:
        used: list[bool] = row["used"]
        return sum(used) / len(used)

    def summary(selected: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        per_question: dict[str, list[float]] = {}
        for row in selected:
            per_question.setdefault(row["question"], []).append(share(row))
        means = [metrics.mean(values) for values in per_question.values()]
        low, high = metrics.bootstrap_interval(means, seed=SEED)
        used = sum(sum(row["used"]) for row in selected)
        return {"used": used / sum(len(row["used"]) for row in selected),
                "low": low, "high": high, "requests": len(selected)}  # fmt: skip

    by_key = {(r["question"], r["size"], r["position"]): r for r in rows}
    sizes = sorted({row["size"] for row in rows})
    found: dict[str, Any] = {"sizes": {}, "budget": sizes[0]}
    passing = True
    for size in sizes:
        selected = [row for row in rows if row["size"] == size]
        entry: dict[str, Any] = summary(selected)
        entry["positions"] = {
            position: summary([r for r in selected if r["position"] == position])
            for position in POSITIONS
        }
        pairs = [
            (share(row), share(by_key[(row["question"], sizes[0], row["position"])]))
            for row in selected
        ]
        entry["against_smallest"] = metrics.paired_cluster_bootstrap(
            [new for new, _ in pairs],
            [old for _, old in pairs],
            [row["question"] for row in selected],
            seed=SEED,
        )
        passing = passing and entry["against_smallest"]["low"] > BUDGET_MARGIN
        if passing:
            found["budget"] = size
        found["sizes"][str(size)] = entry
    return found


# M4: prompt reuse per chat turn.


def reference_reply(turn: Mapping[str, Any]) -> str:
    """What the assistant is taken to have said in an earlier turn (reference mode,
    as X36): the fixed referral after an emergency, else the key's expected answer,
    else the insufficient-evidence text."""
    if turn["expected_status"] == "safety_referral":
        return answer.SAFETY_REFERRAL
    return str(turn.get("expected_answer") or answer.INSUFFICIENT)


def understanding_user(
    turns: Sequence[Mapping[str, Any]], index: int, window: int
) -> str:
    """The stand-in understanding request's user message for turn `index`: the last
    `window` turns, then the new message; with no history, exactly today's."""
    lines = []
    for turn in turns[max(0, index - window) : index]:
        lines.append(f"Customer: {turn['message']}")
        lines.append(f"Assistant: {reference_reply(turn)}")
    question = f"Question: {turns[index]['message']}"
    if not lines:
        return question
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n" + question


def conversation_requests(
    key: Mapping[str, Any], window: int, answers: Sequence[Request]
) -> list[Request]:
    """Every turn's understanding request in conversation order, each followed by
    the next of `answers` (cycled; one output token) when answers are given, as the
    one slot serves understanding then answering."""
    requests: list[Request] = []
    answered = 0
    for conversation in key["conversations"]:
        turns = conversation["turns"]
        for index, turn in enumerate(turns):
            requests.append({
                "id": f"{turn['id']}/understand",
                "system": answer.EXPOSURE_PROMPT,
                "user": understanding_user(turns, index, window),
                "schema": answer.EXPOSURE_SCHEMA,
                "data": {"turn": index + 1},
            })  # fmt: skip
            if answers:
                chosen = answers[answered % len(answers)]
                requests.append(
                    {**chosen, "id": f"{turn['id']}/answer", "max_tokens": 1}
                )
                answered += 1
    return requests


def reuse(requests: Sequence[Request], replies: Sequence[Reply]) -> dict[str, Any]:
    """Understanding requests' prompt tokens, tokens processed and reused, and
    prompt seconds: first turns against later turns."""
    turn_of = {r["id"]: r["data"]["turn"] for r in requests if "data" in r}
    groups: dict[str, list[dict[str, Any]]] = {"first": [], "later": []}
    for reply in replies:
        if reply["id"] in turn_of:
            group = "first" if turn_of[reply["id"]] == 1 else "later"
            groups[group].append(reply["timings"])
    found = {}
    for name, timings in groups.items():
        processed = sum(t["prompt_n"] for t in timings)
        cached = sum(t["cache_n"] for t in timings)
        found[name] = {
            "turns": len(timings),
            "mean_prompt_tokens": (processed + cached) / len(timings),
            "mean_processed": processed / len(timings),
            "reused": cached / (processed + cached),
            "mean_prompt_seconds": sum(t["prompt_ms"] for t in timings)
            / 1000
            / len(timings),
        }
    return found

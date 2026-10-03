"""X40: the support servers' workloads, run through the production call paths
(`llm.embed`, `llm.rerank`) against one server, with its outputs, times, retry warnings
and its own GPU memory, so arms can be compared on equal terms.
"""

import math
import subprocess
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from limespec import config

MIB = 1024 * 1024
CONCURRENCY = 4  # part (c): as many requests at once as the auto slot count
# llama-server's warning when concurrent inputs oversubscribe a unified KV buffer.
KV_FULL = "failed to find free space in the KV cache"

Embed = Callable[[list[str]], list[list[float]]]
Rerank = Callable[[str, list[str]], list[float]]
Run = Callable[..., subprocess.CompletedProcess[str]]


def gpu_process_mib(pid: int, run: Run = subprocess.run) -> float:
    """A process's dedicated GPU memory in MiB, from Windows' GPU Process Memory
    counters (under WDDM, nvidia-smi reports N/A per process)."""
    counter = f"\\GPU Process Memory(pid_{pid}_*)\\Dedicated Usage"
    command = (
        f"((Get-Counter '{counter}').CounterSamples | "
        "Measure-Object CookedValue -Sum).Sum"
    )
    output = run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(output or 0) / MIB


def kv_full_lines(log: str) -> int:
    """How often the server had to retry a batch because its KV cache was full."""
    return sum(KV_FULL in line for line in log.splitlines())


def timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def embed_workload(
    texts: Sequence[str], queries: Sequence[str], embed: Embed
) -> dict[str, Any]:
    """(a) every text in ingestion batches, (b) each query alone, (c) the queries
    `CONCURRENCY` at a time. Vectors: the texts', then the queries' from (b)."""
    size = config.EMBEDDING_BATCH_SIZE
    batches = [list(texts[i : i + size]) for i in range(0, len(texts), size)]
    vectors, ingest = timed(lambda: [v for batch in batches for v in embed(batch)])
    singles = [timed(partial(embed, [query])) for query in queries]
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        _, together = timed(lambda: list(pool.map(lambda q: embed([q]), queries)))
    seconds = [taken for _, taken in singles]
    return {
        "ingest_seconds": ingest,
        "query_p50": percentile(seconds, 0.5),
        "query_p95": percentile(seconds, 0.95),
        "concurrent_seconds": together,
        "vectors": vectors + [found[0] for found, _ in singles],
    }


def rerank_workload(
    calls: Sequence[tuple[str, list[str]]],
    deep: tuple[str, list[str]],
    rerank: Rerank,
) -> dict[str, Any]:
    """(a) each call alone, (b) one deep call, (c) the calls `CONCURRENCY` at a time.
    Scores: (a)'s, then the deep call's."""
    singles = [timed(partial(rerank, *call)) for call in calls]
    deep_scores, deep_seconds = timed(lambda: rerank(*deep))
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        _, together = timed(lambda: list(pool.map(lambda c: rerank(*c), calls)))
    seconds = [taken for _, taken in singles]
    return {
        "call_p50": percentile(seconds, 0.5),
        "call_p95": percentile(seconds, 0.95),
        "deep_seconds": deep_seconds,
        "concurrent_seconds": together,
        "scores": [scores for scores, _ in singles] + [deep_scores],
    }


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def same_vectors(
    base: Sequence[Sequence[float]], arm: Sequence[Sequence[float]]
) -> float:
    """The lowest cosine similarity between each pair of vectors."""
    return min(cosine(a, b) for a, b in zip(base, arm, strict=True))


def same_scores(
    base: Sequence[Sequence[float]], arm: Sequence[Sequence[float]]
) -> dict[str, float]:
    """The largest score difference, and the calls whose candidates come out in a
    different order."""
    largest = 0.0
    reordered = 0
    for first, second in zip(base, arm, strict=True):
        for a, b in zip(first, second, strict=True):
            largest = max(largest, abs(a - b))
        reordered += ranking(first) != ranking(second)
    return {"largest_difference": largest, "reordered": reordered}


def ranking(scores: Sequence[float]) -> list[int]:
    """Candidate positions, best score first (ties keep their order)."""
    return sorted(range(len(scores)), key=lambda i: -scores[i])


def smallest_power(tokens: int, floor: int = 512) -> int:
    """The smallest power of two at least `tokens` and at least `floor`."""
    size = floor
    while size < tokens:
        size *= 2
    return size

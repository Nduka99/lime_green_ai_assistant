"""Score saved retrieval runs with the measures in `metrics`.

Relevance judgements and rankings are TREC files: `qrels.txt` and one
`run-<method>.txt` per method, so trec_eval, pytrec_eval or ranx give the same
numbers. Each question part is scored on its own; a question counts as covered
only when every one of its parts has evidence in the top k.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation import metrics

METHODS = ("keyword", "vector", "fused", "reranked")
BASELINE = "fused"  # every other method is compared with the fused ranking
KS = (1, 3, 5, 8, 10, 20)
TOP_K = 8  # passages the model is given
DEPTH = 20  # candidates per method; a part with no evidence found ranks DEPTH + 1


@dataclass(frozen=True)
class Part:
    """One question part with evidence, and every method's ranked passage ids."""

    part_id: str  # question id + "p" + part number, e.g. "q001p2"
    question_id: str
    relevant: frozenset[int]
    rankings: dict[str, list[int]]


def question_of(part_id: str) -> str:
    return part_id.rsplit("p", 1)[0]


def read_qrels(path: Path) -> dict[str, list[int]]:
    """Part id -> relevant passage ids, in file order."""
    relevant: dict[str, list[int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        part_id, _, passage_id, _ = line.split()
        relevant.setdefault(part_id, []).append(int(passage_id))
    return relevant


def read_run(path: Path) -> dict[str, list[int]]:
    """Part id -> passage ids in rank order."""
    ranked: dict[str, list[int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        part_id, _, passage_id, _, _, _ = line.split()
        ranked.setdefault(part_id, []).append(int(passage_id))
    return ranked


def run_methods(folder: Path) -> list[str]:
    """The methods with a run file: the standard four first, then any others."""
    found = sorted(path.stem.removeprefix("run-") for path in folder.glob("run-*.txt"))
    return [m for m in METHODS if m in found] + [m for m in found if m not in METHODS]


def load(folder: Path) -> list[Part]:
    """Every judged part with each method's ranking, in qrels order."""
    runs = {
        method: read_run(folder / f"run-{method}.txt") for method in run_methods(folder)
    }
    return [
        Part(
            part_id=part_id,
            question_id=question_of(part_id),
            relevant=frozenset(ids),
            rankings={
                method: ranked.get(part_id, []) for method, ranked in runs.items()
            },
        )
        for part_id, ids in read_qrels(folder / "qrels.txt").items()
    ]


def write(parts: list[Part], folder: Path) -> None:
    """The qrels and run files for these parts (scores are 1 / rank)."""
    folder.mkdir(parents=True, exist_ok=True)
    qrels = [f"{p.part_id} 0 {pid} 1" for p in parts for pid in sorted(p.relevant)]
    write_lines(folder / "qrels.txt", qrels)
    for method in parts[0].rankings if parts else ():
        lines = [
            f"{p.part_id} Q0 {pid} {rank} {1 / rank:.6f} {method}"
            for p in parts
            for rank, pid in enumerate(p.rankings[method], 1)
        ]
        write_lines(folder / f"run-{method}.txt", lines)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def per_part(parts: list[Part], method: str) -> dict[str, list[float]]:
    """Each measure's value for every part, in part order."""
    values: dict[str, list[float]] = {f"success_at_{k}": [] for k in KS}
    for name in ("recall_at_8", "precision_at_8", "mrr_at_10", "ndcg_at_10"):
        values[name] = []
    values["first_rank"] = []
    for part in parts:
        ranking, relevant = part.rankings[method], set(part.relevant)
        for k in KS:
            values[f"success_at_{k}"].append(metrics.success_at_k(ranking, relevant, k))
        values["recall_at_8"].append(metrics.recall_at_k(ranking, relevant, TOP_K))
        values["precision_at_8"].append(
            metrics.precision_at_k(ranking, relevant, TOP_K)
        )
        values["mrr_at_10"].append(metrics.reciprocal_rank(ranking, relevant, 10))
        values["ndcg_at_10"].append(metrics.ndcg_at_k(ranking, relevant, 10))
        rank = metrics.first_relevant_rank(ranking, relevant)
        values["first_rank"].append(float(rank) if rank else float(DEPTH + 1))
    return values


def every_part(parts: list[Part], method: str, k: int) -> list[float]:
    """Per question, in id order: 1.0 when every part has evidence in the top k."""
    covered: dict[str, bool] = {}
    for part in parts:
        hit = metrics.success_at_k(part.rankings[method], set(part.relevant), k) == 1.0
        covered[part.question_id] = covered.get(part.question_id, True) and hit
    return [float(covered[question]) for question in sorted(covered)]


def score(parts: list[Part], baseline: str = BASELINE) -> dict[str, Any]:
    """Every measure per method, with intervals, and each method compared with the
    baseline on the same parts (paired bootstrap)."""
    methods = list(parts[0].rankings) if parts else []
    if methods and baseline not in methods:
        raise ValueError(f"no run file for the baseline method {baseline!r}")
    values = {method: per_part(parts, method) for method in methods}
    covered = {method: every_part(parts, method, TOP_K) for method in methods}
    summary: dict[str, Any] = {}
    for method in methods:
        found = values[method]
        low, high = metrics.bootstrap_interval(found[f"success_at_{TOP_K}"])
        summary[method] = {
            **{f"success_at_{k}": metrics.mean(found[f"success_at_{k}"]) for k in KS},
            "success_at_8_interval": [low, high],
            "recall_at_8": metrics.mean(found["recall_at_8"]),
            "precision_at_8": metrics.mean(found["precision_at_8"]),
            "mrr_at_10": metrics.mean(found["mrr_at_10"]),
            "ndcg_at_10": metrics.mean(found["ndcg_at_10"]),
            "median_first_rank": metrics.median(found["first_rank"]),
            "every_part_at_8": metrics.mean(covered[method]),
            "every_part_at_8_count": sum(covered[method]),
            "every_part_at_1_count": sum(every_part(parts, method, 1)),
        }
    # measure -> method -> one value per part (or per question for every_part_at_8)
    compared = {
        "success_at_8": {m: values[m][f"success_at_{TOP_K}"] for m in methods},
        "ndcg_at_10": {m: values[m]["ndcg_at_10"] for m in methods},
        "mrr_at_10": {m: values[m]["mrr_at_10"] for m in methods},
        "every_part_at_8": covered,
    }
    comparisons = [
        {
            "metric": name,
            "pair": f"{method} vs {baseline}",
            **metrics.paired_bootstrap(by_method[method], by_method[baseline]),
        }
        for name, by_method in compared.items()
        for method in methods
        if method != baseline
    ]
    return {
        "methods": summary,
        "comparisons": comparisons,
        "questions": len({part.question_id for part in parts}),
        "parts": len(parts),
    }


def markdown(result: dict[str, Any], set_name: str) -> str:
    methods = list(result["methods"])
    lines = [
        f"{set_name}: {result['questions']} questions, {result['parts']} question "
        "parts with evidence.",
        "",
        "| Method | Success@1 | Success@5 | Success@8 | Success@20 | Recall@8 "
        "| nDCG@10 | MRR@10 | Median rank | Every part @8 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for method in methods:
        m = result["methods"][method]
        lines.append(
            f"| {method} | {m['success_at_1']:.3f} | {m['success_at_5']:.3f} | "
            f"{m['success_at_8']:.3f} | {m['success_at_20']:.3f} | "
            f"{m['recall_at_8']:.3f} | {m['ndcg_at_10']:.3f} | {m['mrr_at_10']:.3f} | "
            f"{m['median_first_rank']:.0f} | {m['every_part_at_8']:.3f} |"
        )
    counts = ", ".join(
        f"{m} {result['methods'][m]['every_part_at_8_count']:.0f}" for m in methods
    )
    firsts = ", ".join(
        f"{m} {result['methods'][m]['every_part_at_1_count']:.0f}" for m in methods
    )
    lines += [
        "",
        f"Questions where every part's evidence reached the model (of "
        f"{result['questions']}): {counts}. Ranked first: {firsts}.",
        "",
        "| Comparison | Metric | Difference | 95% interval | p |",
        "|---|---|---|---|---|",
    ]
    for row in result["comparisons"]:
        lines.append(
            f"| {row['pair']} | {row['metric']} | {row['difference']:+.3f} | "
            f"[{row['low']:+.3f}, {row['high']:+.3f}] | {row['p_value']:.3f} |"
        )
    return "\n".join(lines) + "\n"

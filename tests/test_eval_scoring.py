"""The harness's scoring: retrieval measures, TREC files and graded answers.

Every set here is invented; the real keys stay in git-ignored data/eval/.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from evaluation import grades, metrics, retrieval

RANKING = [5, 9, 3, 7, 1]
RELEVANT = {3, 7}


def test_rank_hit_recall_and_precision() -> None:
    assert metrics.first_relevant_rank(RANKING, RELEVANT) == 3
    assert metrics.first_relevant_rank(RANKING, {99}) is None
    assert metrics.success_at_k(RANKING, RELEVANT, 2) == 0.0
    assert metrics.success_at_k(RANKING, RELEVANT, 3) == 1.0
    assert metrics.recall_at_k(RANKING, RELEVANT, 4) == 1.0
    assert metrics.recall_at_k(RANKING, RELEVANT, 3) == 0.5
    assert metrics.recall_at_k(RANKING, set(), 3) == 0.0
    assert metrics.precision_at_k(RANKING, RELEVANT, 4) == 0.5
    assert metrics.precision_at_k(RANKING, RELEVANT, 0) == 0.0


def test_reciprocal_rank_and_ndcg_match_their_definitions() -> None:
    assert metrics.reciprocal_rank(RANKING, RELEVANT, 10) == 1 / 3
    assert metrics.reciprocal_rank(RANKING, RELEVANT, 2) == 0.0
    # Relevant at ranks 3 and 4; the best possible order puts them at 1 and 2.
    gains = 1 / math.log2(4) + 1 / math.log2(5)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert metrics.ndcg_at_k(RANKING, RELEVANT, 5) == gains / ideal
    assert metrics.ndcg_at_k([1, 2], {1}, 2) == 1.0
    assert metrics.ndcg_at_k([1, 2], set(), 2) == 0.0


def test_mean_median_and_interval() -> None:
    assert metrics.mean([]) == 0.0
    assert metrics.median([]) == 0.0
    assert metrics.median([3.0, 1.0, 2.0]) == 2.0
    assert metrics.median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert metrics.bootstrap_interval([]) == (0.0, 0.0)
    assert metrics.bootstrap_interval([1.0] * 20, rounds=200) == (1.0, 1.0)


def test_paired_bootstrap_finds_a_real_difference_and_ignores_none() -> None:
    better = [1.0] * 30 + [0.0] * 5
    baseline = [0.0] * 35
    result = metrics.paired_bootstrap(better, baseline, rounds=2000)
    assert result["difference"] > 0.8
    assert result["low"] > 0.6
    assert result["p_value"] < 0.05
    same = metrics.paired_bootstrap(baseline, baseline, rounds=2000)
    assert same["difference"] == 0.0
    assert same["p_value"] > 0.05


def parts() -> list[retrieval.Part]:
    """Question q1 has two parts, q2 one; reranking finds more than keyword."""
    return [
        retrieval.Part("q1p1", "q1", frozenset({3}), {"keyword": [9, 3], "fused": [3]}),
        retrieval.Part("q1p2", "q1", frozenset({4}), {"keyword": [9], "fused": [5, 4]}),
        retrieval.Part("q2p1", "q2", frozenset({7}), {"keyword": [7], "fused": [7]}),
    ]


def test_trec_files_round_trip(tmp_path: Path) -> None:
    retrieval.write(parts(), tmp_path)

    assert (tmp_path / "qrels.txt").read_text().splitlines()[0] == "q1p1 0 3 1"
    assert retrieval.load(tmp_path) == parts()


def test_an_empty_run_writes_only_empty_qrels(tmp_path: Path) -> None:
    retrieval.write([], tmp_path)

    assert (tmp_path / "qrels.txt").read_text() == "\n"
    assert not (tmp_path / "run-fused.txt").exists()


def test_a_part_missing_from_a_run_has_an_empty_ranking(tmp_path: Path) -> None:
    (tmp_path / "qrels.txt").write_text("q1p1 0 3 1\n")
    (tmp_path / "run-fused.txt").write_text("q9p1 Q0 3 1 1.000000 fused\n")

    [part] = retrieval.load(tmp_path)
    assert part.question_id == "q1"
    assert part.rankings == {"fused": []}


def test_score_counts_parts_questions_and_whole_questions_covered() -> None:
    result = retrieval.score(parts())

    assert (result["questions"], result["parts"]) == (2, 3)
    keyword, fused = result["methods"]["keyword"], result["methods"]["fused"]
    assert keyword["success_at_8"] == 2 / 3  # q1p2's evidence is never found
    assert fused["success_at_8"] == 1.0
    assert keyword["median_first_rank"] == 2.0
    assert keyword["every_part_at_8_count"] == 1.0  # only q2
    assert fused["every_part_at_8_count"] == 2.0
    assert fused["every_part_at_1_count"] == 1.0  # q1p2 ranks second
    pairs = {(row["metric"], row["pair"]) for row in result["comparisons"]}
    assert ("every_part_at_8", "keyword vs fused") in pairs
    assert len(pairs) == 4  # four measures, one method against the baseline


def test_other_methods_follow_the_standard_four_and_need_the_baseline(
    tmp_path: Path,
) -> None:
    for method in ("pg-hybrid", "fused", "keyword"):
        (tmp_path / f"run-{method}.txt").write_text("q1p1 Q0 3 1 1.000000 x\n")

    assert retrieval.run_methods(tmp_path) == ["keyword", "fused", "pg-hybrid"]
    with pytest.raises(ValueError, match="baseline method 'vector'"):
        retrieval.score(parts(), baseline="vector")
    assert retrieval.score([])["parts"] == 0


def test_markdown_names_the_set_and_every_method() -> None:
    text = retrieval.markdown(retrieval.score(parts()), "demo")

    assert text.startswith("demo: 2 questions, 3 question parts with evidence.")
    assert "| keyword | 0.333 | 0.667 | 0.667 |" in text  # Success@1, @5, @8
    assert "| keyword vs fused | success_at_8 |" in text


KEY: dict[str, Any] = {
    "cases": [
        {
            "id": "joints",
            "type": "single",
            "expected_status": "answered",
            "wordings": [
                {"style": "original", "text": "What joints does Mortex suit?"},
                {"style": "rushed", "text": "mortex joints?"},
            ],
        },
        {
            "id": "price",
            "type": "refusal",
            "expected_status": "insufficient_evidence",
            "wordings": [
                {"style": "original", "text": "What does Mortex cost?"},
                {"style": "rushed", "text": "mortex price"},
            ],
        },
    ]
}
QUESTIONS = [
    {"id": "t001", "question": "mortex price"},
    {"id": "t002", "question": "What joints does Mortex suit?"},
    {"id": "t003", "question": "mortex joints?"},
    {"id": "t004", "question": "What does Mortex cost?"},
]


def test_questions_map_to_their_case_and_style_by_text() -> None:
    cases = grades.cases_by_question(KEY, QUESTIONS)

    assert cases["t001"][0]["id"] == "price"
    assert cases["t001"][1] == "rushed"


def test_frozen90s_key_shape_maps_too() -> None:
    key = {
        "cases": [
            {"id": "eye", "type": "emergency", "expected_status": ["safety_referral"],
             "questions": [{"style": "original", "text": "Lime went in my eye"}]},
        ]
    }  # fmt: skip

    cases = grades.cases_by_question(
        key, [{"id": "f001", "question": "Lime went in my eye"}]
    )

    assert cases["f001"] == (key["cases"][0], "original")
    assert grades.expected_statuses(cases["f001"][0]) == {"safety_referral"}


def test_a_question_not_in_the_key_or_in_it_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="t009 matches 0 wordings"):
        grades.cases_by_question(KEY, [{"id": "t009", "question": "unknown"}])
    doubled = {"cases": [KEY["cases"][0], KEY["cases"][0]]}
    with pytest.raises(ValueError, match="matches 2 wordings"):
        grades.cases_by_question(doubled, QUESTIONS[1:2])


def test_counts_refuse_an_unknown_verdict() -> None:
    assert grades.counts(["sound", "wrong", "sound"]) == {
        "sound": 2,
        "partial": 0,
        "wrong": 1,
    }
    with pytest.raises(ValueError, match="unknown verdicts"):
        grades.counts(["good"])


def sitting() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    verdicts = {"t001": "sound", "t002": "partial", "t003": "sound", "t004": "wrong"}
    graded = {
        qid: {"v5": {"verdict": v}, "v6": {"verdict": "sound"}}
        for qid, v in verdicts.items()
    }
    refused = {"status": "insufficient_evidence", "notice": "fixed"}
    answered = {"status": "answered", "notice": ""}
    answers = {
        "v5": {
            "t001": {"view": refused, "seconds": 10.0},
            "t002": {"view": answered, "seconds": 20.0},
            "t003": {"error": "HTTP 503", "seconds": 1.0},
            "t004": {"view": answered, "seconds": 30.0},
        },
        "v6": {qid: {"view": answered, "seconds": 5.0} for qid in verdicts},
    }
    return graded, answers


def test_score_groups_by_case_type_and_wording_style() -> None:
    graded, answers = sitting()

    result = grades.score(KEY, QUESTIONS, graded, answers)

    by_name = {group["name"]: group for group in result["groups"]}
    assert list(by_name) == [
        "All",
        "Type: refusal",
        "Type: single",
        "Wording: rushed",
        "Wording: original",
    ]
    assert by_name["All"]["counts"]["v5"] == {"sound": 2, "partial": 1, "wrong": 1}
    assert by_name["Type: refusal"]["counts"]["v5"]["wrong"] == 1
    # t001 refused as expected; t002 answered; the error record has no status.
    assert result["status_matched"] == {"v5": 2, "v6": 2}
    assert result["cautions"] == {"v5": 1, "v6": 0}
    assert result["median_seconds"]["v5"] == 15.0


def test_a_sitting_folder_loads_grades_and_each_arms_answers(tmp_path: Path) -> None:
    graded, answers = sitting()
    (tmp_path / "grades.json").write_text(json.dumps(graded))
    for arm, records in answers.items():
        rows = [{"id": qid, **record} for qid, record in records.items()]
        (tmp_path / f"answers-{arm}.json").write_text(json.dumps(rows))

    loaded_grades, loaded_answers = grades.load_sitting(tmp_path)

    assert loaded_grades == graded
    assert list(loaded_answers) == ["v5", "v6"]
    assert loaded_answers["v5"]["t003"]["error"] == "HTTP 503"


def test_grades_markdown_lists_counts_status_and_time() -> None:
    graded, answers = sitting()

    text = grades.markdown(grades.score(KEY, QUESTIONS, graded, answers), "demo")

    assert text.startswith("demo: 4 answers per arm, sound / partial / wrong.")
    assert "| All | 4 | 2 / 1 / 1 | 4 / 0 / 0 |" in text
    assert "| v5 | 2/4 | 1 | 15.0 |" in text

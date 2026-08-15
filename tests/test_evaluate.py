from __future__ import annotations

from scotoma.evaluate import _metrics, evaluate_rankers


def test_metrics_reward_relevant_files_at_top() -> None:
    result = _metrics(["a.py", "b.py", "c.py"], {"a.py", "b.py"})

    assert result["recall_at_2"] == 1.0
    assert result["mrr"] == 1.0
    assert result["ndcg_at_5"] == 1.0


def test_evaluation_compares_all_four_rankers() -> None:
    coverage = {
        "units": [
            {"path": "wrong.py", "sem": 0.9, "blind_risk": 0.9},
            {"path": "truth.py", "sem": 1.0, "blind_risk": 0.2},
        ]
    }
    adjudication = {
        "ranked_candidates": [
            {"path": "truth.py", "verdict": "contradicts"},
            {"path": "wrong.py", "verdict": "irrelevant"},
        ]
    }

    result = evaluate_rankers(coverage, adjudication, random_trials=10)

    assert set(result["rankers"]) == {
        "random",
        "semantic_only",
        "three_signal_composite",
        "claim_adjudicated",
    }
    assert result["rankers"]["claim_adjudicated"]["mrr"] == 1.0

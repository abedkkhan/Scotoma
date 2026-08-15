"""Offline ranking evaluation using flip-verified contradictory evidence."""

from __future__ import annotations

import math
import random
from typing import Any


def _metrics(ranking: list[str], relevant: set[str], k: int = 5) -> dict[str, float]:
    ranks = [index for index, path in enumerate(ranking, start=1) if path in relevant]
    recall_at_2 = sum(rank <= 2 for rank in ranks) / len(relevant) if relevant else 0.0
    reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks if rank <= k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return {
        "recall_at_2": round(recall_at_2, 4),
        "mrr": round(reciprocal_rank, 4),
        "ndcg_at_5": round(dcg / ideal if ideal else 0.0, 4),
        "relevant_ranks": ranks,
    }


def evaluate_rankers(
    coverage: dict[str, Any], adjudication: dict[str, Any], random_trials: int = 1000
) -> dict[str, Any]:
    relevant = {
        item["path"]
        for item in adjudication["ranked_candidates"]
        if item["verdict"] == "contradicts"
    }
    paths = [unit["path"] for unit in coverage["units"]]
    semantic = [
        unit["path"]
        for unit in sorted(coverage["units"], key=lambda item: (-item["sem"], item["path"]))
    ]
    composite = [
        unit["path"]
        for unit in sorted(
            coverage["units"], key=lambda item: (-item["blind_risk"], item["path"])
        )
    ]
    adjudicated_head = [item["path"] for item in adjudication["ranked_candidates"]]
    adjudicated = adjudicated_head + [path for path in composite if path not in adjudicated_head]

    rng = random.Random(42)
    random_scores: list[dict[str, float]] = []
    for _ in range(random_trials):
        sample = paths.copy()
        rng.shuffle(sample)
        random_scores.append(_metrics(sample, relevant))
    random_average = {
        key: round(sum(score[key] for score in random_scores) / random_trials, 4)
        for key in ("recall_at_2", "mrr", "ndcg_at_5")
    }

    return {
        "ground_truth": sorted(relevant),
        "ground_truth_basis": "Files adjudicated as contradictory and verified by the conclusion flip test.",
        "random_trials": random_trials,
        "rankers": {
            "random": random_average,
            "semantic_only": _metrics(semantic, relevant),
            "three_signal_composite": _metrics(composite, relevant),
            "claim_adjudicated": _metrics(adjudicated, relevant),
        },
    }

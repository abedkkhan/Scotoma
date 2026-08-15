from __future__ import annotations

from scotoma.adjudicate import _normalize_judgment, select_candidates


def test_candidate_union_preserves_high_relevance_partial_file() -> None:
    units = [
        {
            "path": f"file_{index}.py",
            "blind_risk": 1.0 - index / 100,
            "relevance": 1.0 - index / 100,
            "depth": 0.0,
        }
        for index in range(20)
    ]
    critical = {
        "path": "sessions.py",
        "blind_risk": 0.1,
        "relevance": 2.0,
        "depth": 0.6,
    }
    units.append(critical)

    candidates = select_candidates({"units": units}, count=15)

    assert len(candidates) == 15
    assert "sessions.py" in {item["path"] for item in candidates}


def test_judgment_normalization_clamps_and_validates_fields() -> None:
    result = _normalize_judgment(
        {
            "overturn_probability": 4,
            "target_claim_id": "missing",
            "verdict": "UNKNOWN",
            "reason": "one two three",
        },
        {"C1"},
    )

    assert result["overturn_probability"] == 0.05
    assert result["target_claim_id"] is None
    assert result["verdict"] == "irrelevant"

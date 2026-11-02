"""Calibration view: the system audits its own judge.

Joins sealed judgments (log) with human outcomes, then reports how well the
recorded probabilities predicted reality — per score bucket, per model.

v1 scope, stated honestly:
* only `admit` entries are calibrated (p_admit vs whether admitting was right);
* `review`/`exclude` outcomes are recorded but not yet scored;
* orphan outcomes (judgment not in the log) are counted, never silently dropped.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Mapping, Optional, Sequence

BUCKETS = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9),
           (0.9, 1.0001))


def _bucket(p: float) -> str:
    for low, high in BUCKETS:
        if low <= p < high:
            return f"[{low:.1f},{high:.1f})"
    return f"[0.9,1.0]"


def calibrate(judgments: Sequence[Mapping[str, Any]],
              outcomes: Sequence[Mapping[str, Any]], *,
              action: str = "admit") -> Dict[str, Any]:
    by_hash = {j.get("judgment_hash"): j for j in judgments}
    pairs: List[Dict[str, Any]] = []
    orphans = 0
    unsupported = 0

    for outcome in outcomes:
        judgment = by_hash.get(outcome.get("judgment_hash"))
        if judgment is None:
            orphans += 1
            continue
        record_id = outcome.get("record_id")
        entry = next((e for e in judgment.get("entries", [])
                      if e.get("record_id") == record_id), None)
        if entry is None:
            unsupported += 1
            continue
        if entry.get("action") != action or entry.get("p_admit") is None:
            unsupported += 1
            continue
        verdict = outcome.get("verdict")
        if verdict not in ("upheld", "overturned"):
            unsupported += 1
            continue
        was_right = 1.0 if verdict == "upheld" else 0.0
        pairs.append({
            "p_admit": float(entry["p_admit"]),
            "was_right": was_right,
            "verdict": verdict,
            "model": judgment.get("model", "?"),
            "judgment_hash": outcome.get("judgment_hash"),
            "record_id": record_id,
        })

    scored = [p for p in pairs]
    brier = (round(statistics.mean(
        (p["p_admit"] - p["was_right"]) ** 2 for p in scored), 4)
        if scored else None)

    buckets: Dict[str, Dict[str, Any]] = {}
    for low, high in BUCKETS:
        inside = [p for p in scored if low <= p["p_admit"] < high]
        buckets[f"[{low:.1f},{high:.1f})" if high <= 1.0 else "[0.9,1.0]"] = {
            "n": len(inside),
            "upheld_rate": (round(sum(p["was_right"] for p in inside) / len(inside), 4)
                            if inside else None),
        }

    by_model: Dict[str, Dict[str, Any]] = {}
    for model in sorted({p["model"] for p in scored}):
        mine = [p for p in scored if p["model"] == model]
        by_model[model] = {
            "n": len(mine),
            "upheld_rate": (round(sum(p["was_right"] for p in mine) / len(mine), 4)
                            if mine else None),
        }

    return {
        "action": action,
        "n_outcomes": len(outcomes),
        "n_scored": len(scored),
        "orphans": orphans,
        "unsupported": unsupported,
        "overall_upheld_rate": (round(sum(p["was_right"] for p in scored)
                                      / len(scored), 4) if scored else None),
        "brier": brier,
        "buckets": buckets,
        "by_model": by_model,
        "pairs": scored,
    }
"""edges_v1 scoring: implements the pre-registered metrics from protocol.md.

    python experiments/edges_v1/score.py

Writes results/score.json. Primary metrics = run 1 only; runs 2-3 = stability.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = ("supports", "contradicts", "supersedes", "unrelated")


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((center - spread) / denom, (center + spread) / denom)


def ci_dict(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    rows = [json.loads(line) for line in
            (ROOT / "results" / "runs.jsonl").read_text().splitlines()
            if line.strip()]
    pairs = [json.loads(line) for line in
             (ROOT / "pairs.jsonl").read_text().splitlines() if line.strip()]
    contested_ids = {p["pair_id"] for p in pairs if not p["in_gold"]}

    by_run = defaultdict(dict)
    for row in rows:
        by_run[row["run"]][row["pair_id"]] = row
    for run, mapping in sorted(by_run.items()):
        missing = [p["pair_id"] for p in pairs
                   if p["pair_id"] not in mapping and p["in_gold"]]
        if missing:
            raise SystemExit(f"run {run}: {len(missing)} gold pairs missing")
        print(f"run {run}: {len(mapping)} rows")

    # ---- primary metrics: run 1, gold pairs only ------------------------
    primary = by_run[0]
    scored = {pid: row for pid, row in primary.items()
              if pid not in contested_ids and row["in_gold"]}
    n = len(scored)
    correct = sum(1 for r in scored.values() if r["label"] == r["gold"])

    confusion = {g: {p: 0 for p in LABELS} for g in ("supports", "contradicts", "unrelated")}
    for r in scored.values():
        confusion[r["gold"]][r["label"]] += 1

    per_class = {}
    for gold_label in ("supports", "contradicts", "unrelated"):
        tp = confusion[gold_label][gold_label]
        fn = sum(confusion[gold_label][p] for p in LABELS) - tp
        fp = sum(confusion[g][gold_label] for g in confusion) - tp
        per_class[gold_label] = {
            "recall": ci_dict(tp, tp + fn),
            "precision": ci_dict(tp, tp + fp),
        }

    buckets = {"p>=0.90": [], "0.80-0.89": [], "<0.80": []}
    for r in scored.values():
        p = max(r["probs"].values())
        key = "p>=0.90" if p >= 0.90 else ("0.80-0.89" if p >= 0.80 else "<0.80")
        buckets[key].append(r["label"] == r["gold"])
    calibration = {k: ci_dict(sum(v), len(v)) for k, v in buckets.items()}

    # ---- stability across runs ------------------------------------------
    labels_by_pair = defaultdict(set)
    for run, mapping in by_run.items():
        for pid, r in mapping.items():
            if pid not in contested_ids and r["in_gold"]:
                labels_by_pair[pid].add(r["label"] if r["parse"] else "PARSE_ERROR")
    unstable = [pid for pid, labels in labels_by_pair.items() if len(labels) > 1]

    # ---- contested pairs behavior ----------------------------------------
    contested = []
    for pid in sorted(contested_ids):
        row = primary[pid]
        contested.append({
            "pair_id": pid,
            "run1_label": row["label"], "run1_p": max(row["probs"].values()),
            "labels_across_runs": sorted(labels_by_pair.get(pid, set())) or
                                  sorted({by_run[r][pid]["label"] for r in by_run}),
            "contested_channel_labels": next(
                p["contested"] for p in pairs if p["pair_id"] == pid),
        })

    # ---- gates ------------------------------------------------------------
    h1 = ci_dict(correct, n)
    h2 = per_class["contradicts"]["recall"]
    h3 = per_class["contradicts"]["precision"]
    h4 = per_class["unrelated"]["recall"]
    supersedes_predicted = sum(1 for r in scored.values() if r["label"] == "supersedes")
    gates = {
        "P2-H1_accuracy>=0.80": {"metric": h1,
                                 "pass": bool(h1["n"] and h1["rate"] >= 0.80)},
        "P2-H2_contradicts_recall=5/5": {"metric": h2,
                                         "pass": bool(h2["n"] and h2["k"] == 5)},
        "P2-H3_contradicts_precision=5/5": {"metric": h3,
                                            "pass": bool(h3["n"] and h3["k"] == 5)},
        "P2-H4_unrelated_recall>=0.90": {"metric": h4,
                                         "pass": bool(h4["n"] and h4["rate"] >= 0.90)},
        "supersedes_predicted_on_gold": {"k": supersedes_predicted,
                                         "note": "directional; zero gold supersedes"},
    }

    result = {
        "schema": "edges_v1_score_v1",
        "n_scored": n,
        "n_contested": len(contested_ids),
        "accuracy_run1": h1,
        "confusion_matrix_predicted_by_gold": confusion,
        "per_class": per_class,
        "calibration_buckets": calibration,
        "stability": {"pairs": len(labels_by_pair), "unstable": len(unstable),
                      "flip_rate": round(len(unstable) / len(labels_by_pair), 4),
                      "unstable_pair_ids": unstable},
        "contested_pairs": contested,
        "gates": gates,
        "parse_failures_run1": sum(1 for r in primary.values() if not r["parse"]),
        "latency_ms_median_run1": sorted(r["latency_ms"] for r in primary.values())[
            len(primary) // 2],
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print(f"accuracy run1: {h1['k']}/{h1['n']} = {h1['rate']}"
          f"  CI95 {h1['ci95']}")
    for g, m in per_class.items():
        print(f"  {g:11s} recall {m['recall']['k']}/{m['recall']['n']}"
              f" = {m['recall']['rate']}  precision {m['precision']['k']}/{m['precision']['n']}"
              f" = {m['precision']['rate']}")
    print(f"stability: {result['stability']['unstable']}/{result['stability']['pairs']} unstable")
    print("gates:", {k: v.get("pass") for k, v in gates.items() if "pass" in v})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

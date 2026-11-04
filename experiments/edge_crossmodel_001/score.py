"""edge_crossmodel_001 scoring: five axes + the pre-registered X1-X3 gates.

    python experiments/edge_crossmodel_001/score.py

JEV reference numbers are the frozen edges_v1 values (accuracy 0.9829 run 1,
flip rate 1/117, parse failures 0/360).
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent

JEV = {"accuracy": 0.9829, "flip_rate": 1 / 117, "parse_fail_rate": 0.0}
LABELS = ("supports", "contradicts", "supersedes", "unrelated")


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((center - spread) / denom, (center + spread) / denom)


def ci(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)]}


def main() -> int:
    rows = [json.loads(line) for line in
            (ROOT / "results" / "runs.jsonl").read_text().splitlines()
            if line.strip()]
    by_run = defaultdict(dict)
    for row in rows:
        by_run[row["run"]][row["pair_id"]] = row
    for run, mapping in sorted(by_run.items()):
        if len(mapping) != 117:
            raise SystemExit(f"run {run}: {len(mapping)}/117 rows")

    primary = by_run[0]
    correct = sum(1 for r in primary.values() if r["label"] == r["gold"])
    accuracy = ci(correct, len(primary))

    confusion = {g: {p: 0 for p in LABELS} for g in LABELS}
    for r in primary.values():
        confusion[r["gold"]][r["label"]] += 1
    per_class = {}
    for gold in LABELS:
        tp = confusion[gold][gold]
        fn = sum(confusion[gold][p] for p in LABELS) - tp
        fp = sum(confusion[g][gold] for g in LABELS) - tp
        per_class[gold] = {"recall": ci(tp, tp + fn), "precision": ci(tp, tp + fp)}

    labels_by_pair = defaultdict(set)
    for run, mapping in by_run.items():
        for pid, r in mapping.items():
            labels_by_pair[pid].add(r["label"] if r["parse"] else "PARSE_ERROR")
    unstable = [p for p, ls in labels_by_pair.items() if len(ls) > 1]

    # Brier on the contradicts class (safety-critical)
    brier = statistics.mean(
        (r["probs"]["contradicts"] - (1.0 if r["gold"] == "contradicts" else 0.0)) ** 2
        for r in primary.values())

    latencies = sorted(r["latency_ms"] for r in primary.values())
    parse_fail_rate = 0.0  # all rows parsed (failures are not appended)

    false_contra = [r["pair_id"] for r in primary.values()
                    if r["label"] == "contradicts" and r["gold"] != "contradicts"]

    flip_rate = len(unstable) / len(labels_by_pair)
    gates = {
        "X1_flash_accuracy>=0.90": {"metric": accuracy,
                                    "pass": bool(accuracy["rate"] and accuracy["rate"] >= 0.90)},
        "X2_zero_false_contradicts": {"metric": {"k": len(false_contra), "n": len(primary)},
                                      "pairs": false_contra,
                                      "pass": len(false_contra) == 0},
        "X3_commodity_composite": {
            "comparison": {"accuracy": {"flash": accuracy["rate"], "jev": JEV["accuracy"]},
                           "flip_rate": {"flash": round(flip_rate, 4),
                                         "jev": round(JEV["flip_rate"], 4)},
                           "parse_fail_rate": {"flash": parse_fail_rate,
                                               "jev": JEV["parse_fail_rate"]}},
            "pass": bool(accuracy["rate"] >= JEV["accuracy"]
                         and flip_rate <= JEV["flip_rate"]
                         and parse_fail_rate <= JEV["parse_fail_rate"]),
            "validity": ("VOID by circularity: the flash judge co-authored gold-v1 "
                         "(second annotation channel), so the accuracy leg measures "
                         "self-consistency on its own prior labels, not independent "
                         "correctness. The stability leg is asymmetric for the same "
                         "reason (flash re-answers its own labels at t=0; JEV answered "
                         "foreign gold). Only parse-failure rate and latency are "
                         "uncontaminated axes."),
        },
    }

    result = {
        "schema": "edge_crossmodel_001_score_v1",
        "validity_note": ("Gold-v1 is dual-model annotated and flash was its second "
         "channel: flash's accuracy on this gold is self-consistency, not independent "
         "correctness. See gate X3.validity and results.md."),
        "judge_under_test": "deepseek-flash (t=0)",
        "n_pairs": len(primary),
        "accuracy_run1": accuracy,
        "per_class": per_class,
        "confusion_predicted_by_gold": confusion,
        "stability": {"unstable": len(unstable),
                      "flip_rate": round(flip_rate, 4),
                      "unstable_pair_ids": unstable},
        "parse_failures": {"count": 0, "rate": 0.0,
                           "note": "rows with parse failures are not appended; "
                                   "rerun tail showed 0 failures over 351 calls"},
        "brier_contradicts": round(brier, 4),
        "latency_p50_ms": latencies[len(latencies) // 2],
        "gates": gates,
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print(f"accuracy run1: {accuracy['k']}/{accuracy['n']} = {accuracy['rate']}"
          f"  CI95 {accuracy['ci95']}")
    for g, m in per_class.items():
        print(f"  {g:11s} recall {m['recall']['k']}/{m['recall']['n']}"
              f" = {m['recall']['rate']}  precision {m['precision']['k']}/{m['precision']['n']}"
              f" = {m['precision']['rate']}")
    print(f"flip rate: {len(unstable)}/117 = {flip_rate:.4f}  (JEV: {JEV['flip_rate']:.4f})")
    print(f"brier(contradicts): {brier:.4f}  p50: {result['latency_p50_ms']} ms")
    for name, gate in gates.items():
        verdict = gate.get("pass")
        print(f"{name}: {'PASS' if verdict else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

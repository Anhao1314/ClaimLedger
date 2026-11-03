#!/usr/bin/env python3
"""Recompute judge_bench_001 metrics from the committed rows, separating genuine
label flips from parse/transport failures.

The original summary conflated "the label changed" with "one run failed to
parse", which inflated every judge's instability and made Jev look like it had
flips when it had transport errors. This analysis does not make new calls: it
only re-reads experiments/judge_bench_001/results.json.
"""
from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path

EXP = Path(__file__).resolve().parents[1] / "experiments" / "judge_bench_001"
RESULTS = EXP / "results.json"


def analyze(name: str, rows: list) -> dict:
    by_id = collections.defaultdict(list)
    for row in rows:
        by_id[row["id"]].append(row["label"] if row["parse"] else None)

    genuine, error_only = [], []
    for pair_id, labels in by_id.items():
        parsed = [label for label in labels if label is not None]
        has_error = any(label is None for label in labels)
        if len(set(parsed)) > 1:
            genuine.append(pair_id)
        elif has_error and parsed:
            error_only.append(pair_id)

    per_run_accuracy = []
    per_run_brier = []
    runs = collections.defaultdict(list)
    for row in rows:
        runs[row["run"]].append(row)
    for run_rows in runs.values():
        scored = [r for r in run_rows if r["parse"]]
        if not scored:
            continue
        per_run_accuracy.append(sum(r["label"] == r["gold"] for r in scored) / len(scored))
        per_run_brier.append(statistics.mean(
            (r["probs"]["contradiction"] - (1.0 if r["gold"] == "contradiction" else 0.0)) ** 2
            for r in scored if r["probs"]))
    tops = sorted(max(r["probs"].values()) for r in rows if r["probs"])
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]

    return {
        "calls": len(rows),
        "parsed": sum(1 for r in rows if r["parse"]),
        "parse_failure_rate": round(1 - sum(1 for r in rows if r["parse"]) / len(rows), 4),
        "accuracy_mean": round(statistics.mean(per_run_accuracy), 4) if per_run_accuracy else None,
        "accuracy_range": [round(min(per_run_accuracy), 4), round(max(per_run_accuracy), 4)]
        if per_run_accuracy else None,
        "genuine_label_flips": {"count": len(genuine), "rate": round(len(genuine) / len(by_id), 4)},
        "error_only_pairs": {"count": len(error_only), "rate": round(len(error_only) / len(by_id), 4)},
        "brier": round(statistics.mean(per_run_brier), 4) if per_run_brier else None,
        "top_probability_p50": round(statistics.median(tops), 4) if tops else None,
        "latency_p50_ms": int(statistics.median(latencies)) if latencies else None,
    }


def main() -> int:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    corrected = {name: analyze(name, rows) for name, rows in data["rows"].items()}

    summary = {
        "schema": "judge_bench_001_corrected_v1",
        "note": ("Recomputed from committed rows. Genuine label flips exclude runs "
                 "that failed to parse; the original summary counted those as flips."),
        "judges": corrected,
    }
    (EXP / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")

    print(f"{'judge':22} {'acc':>6} {'acc range':>12} {'flips':>7} {'err-only':>9} "
          f"{'parse fail':>10} {'Brier':>7} {'top p50':>8} {'p50 ms':>7}")
    for name, s in corrected.items():
        rng = f"{s['accuracy_range'][0]:.2f}-{s['accuracy_range'][1]:.2f}" \
            if s["accuracy_range"] else "-"
        print(f"{name:22} {s['accuracy_mean']:>6} {rng:>12} "
              f"{s['genuine_label_flips']['count']:>7} {s['error_only_pairs']['count']:>9} "
              f"{s['parse_failure_rate']:>10} {str(s['brier']):>7} "
              f"{str(s['top_probability_p50']):>8} {s['latency_p50_ms']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
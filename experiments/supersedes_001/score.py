"""supersedes_001 scoring: implements the pre-registered S1-H1..H5 gates.

    python experiments/supersedes_001/score.py

Writes results/score.json. Primary = run 1; runs 2-3 = stability.
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
    pairs = {json.loads(l)["pair_id"]: json.loads(l)
             for l in (ROOT / "pairs.jsonl").read_text().splitlines()
             if l.strip()}

    by_run = defaultdict(dict)   # run -> pair_id -> row (edge question)
    dir_by_run = defaultdict(dict)  # run -> pair_id -> row (direction question)
    for row in rows:
        target = by_run if row["question"] == "edge" else dir_by_run
        target[row["run"]][row["pair_id"]] = row

    primary = by_run[0]
    label = {pid: r["label"] for pid, r in primary.items()}

    sup_ids = [p for p in pairs if pairs[p]["stratum"] == "supersedes"]
    dis_ids = [p for p in pairs if pairs[p]["stratum"] == "distractor"]
    ctl_ids = [p for p in pairs if pairs[p]["stratum"] == "control"]

    # ---- gates -----------------------------------------------------------
    sup_rec = ci_dict(sum(1 for p in sup_ids if label[p] == "supersedes"),
                      len(sup_ids))
    sup_as_contra = [p for p in sup_ids if label[p] == "contradicts"]
    dis_as_sup = [p for p in dis_ids if label[p] == "supersedes"]
    ctl_as_sup = [p for p in ctl_ids if label[p] == "supersedes"]
    dis_recall = ci_dict(sum(1 for p in dis_ids if label[p] == "contradicts"),
                         len(dis_ids))

    # ---- direction question ----------------------------------------------
    dir_rows = []
    for pid in sup_ids:
        if label[pid] != "supersedes":
            continue
        truth = pairs[pid]["direction_truth"]
        r1 = dir_by_run[0].get(pid)
        if r1 is None:
            continue
        dir_rows.append({"pair_id": pid, "truth": truth, "observed": r1["label"],
                         "p": max(r1["probs"].values()),
                         "correct": r1["label"] == truth})
    dir_correct = sum(1 for d in dir_rows if d["correct"])
    direction = ci_dict(dir_correct, len(dir_rows)) if dir_rows else None

    # ---- stability --------------------------------------------------------
    labels_by_pair = defaultdict(set)
    for run, mapping in by_run.items():
        for pid, r in mapping.items():
            labels_by_pair[pid].add(r["label"] if r["parse"] else "PARSE_ERROR")
    unstable = [p for p, ls in labels_by_pair.items() if len(ls) > 1]
    dir_labels = defaultdict(set)
    for run, mapping in dir_by_run.items():
        for pid, r in mapping.items():
            dir_labels[pid].add(r["label"] if r["parse"] else "PARSE_ERROR")
    dir_unstable = [p for p, ls in dir_labels.items() if len(ls) > 1]

    # ---- calibration on the supersedes set --------------------------------
    buckets = {"p>=0.90": [], "0.80-0.89": [], "<0.80": []}
    for pid in sup_ids:
        p = max(primary[pid]["probs"].values())
        key = "p>=0.90" if p >= 0.90 else ("0.80-0.89" if p >= 0.80 else "<0.80")
        buckets[key].append(label[pid] == "supersedes")
    calibration = {k: ci_dict(sum(v), len(v)) for k, v in buckets.items()}

    result = {
        "schema": "supersedes_001_score_v1",
        "n_pairs": len(pairs),
        "gates": {
            "S1-H1_supersedes_recall>=0.85": {
                "metric": sup_rec, "pass": bool(sup_rec["n"] and sup_rec["rate"] >= 0.85)},
            "S1-H2_zero_supersedes_as_contradicts": {
                "metric": {"k": len(sup_as_contra), "n": len(sup_ids)},
                "pairs": sup_as_contra,
                "pass": len(sup_as_contra) == 0},
            "S1-H3_zero_distractor_as_supersedes": {
                "metric": {"k": len(dis_as_sup), "n": len(dis_ids)},
                "pairs": dis_as_sup,
                "pass": len(dis_as_sup) == 0},
            "S1-H4_zero_control_as_supersedes": {
                "metric": {"k": len(ctl_as_sup), "n": len(ctl_ids)},
                "pairs": ctl_as_sup,
                "pass": len(ctl_as_sup) == 0},
        },
        "supersedes_recall": sup_rec,
        "distractor_contradicts_recall": dis_recall,
        "direction_question": {
            "scored_on": "supersedes-classified pairs, run 1",
            "metric": direction,
            "detail": dir_rows,
            "unstable_across_runs": dir_unstable,
        },
        "supersedes_set_labels": {p: label[p] for p in sup_ids},
        "distractor_set_labels": {p: label[p] for p in dis_ids},
        "control_set_labels": {p: label[p] for p in ctl_ids},
        "stability": {"unstable_pairs": unstable,
                      "flip_rate": round(len(unstable) / len(labels_by_pair), 4)},
        "calibration_supersedes_set": calibration,
        "parse_failures_run1": sum(1 for r in primary.values() if not r["parse"]),
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    for name, gate in result["gates"].items():
        print(f"{name}: {'PASS' if gate['pass'] else 'FAIL'} {gate['metric']}")
    print(f"distractor contradicts recall: {dis_recall['k']}/{dis_recall['n']}")
    if direction:
        print(f"direction: {direction['k']}/{direction['n']} = {direction['rate']}"
              f"  CI95 {direction['ci95']}")
    print(f"stability: {len(unstable)}/{len(labels_by_pair)} unstable; "
          f"direction unstable: {len(dir_unstable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""supersedes_002 scoring: S2-H1..H5 gates + paired v2/v3 delta on the
corrected pairs + regression view on the 21 gold members.

    python experiments/supersedes_002/score.py
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREV = ROOT.parent / "supersedes_001"


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

    by_arm = defaultdict(dict)   # (arm, run) -> pair_id -> row
    for row in rows:
        arm = row["question"]  # v3 | v2 | direction
        by_arm[(arm, row["run"])][row["pair_id"]] = row

    label = {pid: r["label"] for pid, r in by_arm[("v3", 0)].items()}
    sup_ids = [p for p in pairs if pairs[p]["stratum"] == "supersedes"]
    dis_ids = [p for p in pairs if pairs[p]["stratum"] == "distractor"]
    ctl_ids = [p for p in pairs if pairs[p]["stratum"] == "control"]
    # gold members identified by verbatim text match against gold-v1
    # (provenance tags were stripped when carrying pairs from _001)
    gold_texts = {(g["src_text"], g["dst_text"]) for g in
                  (json.loads(l) for l in
                   (PREV.parent / "edges_gold" / "gold-v1.jsonl")
                   .read_text().splitlines() if l.strip())}
    gold_members = [p for p in pairs
                    if (pairs[p]["src_text"], pairs[p]["dst_text"]) in gold_texts]

    sup_rec = ci_dict(sum(1 for p in sup_ids if label[p] == "supersedes"),
                      len(sup_ids))
    sup_as_contra = [p for p in sup_ids if label[p] == "contradicts"]
    dis_as_sup = [p for p in dis_ids if label[p] == "supersedes"]
    ctl_as_sup = [p for p in ctl_ids if label[p] == "supersedes"]
    dis_recall = ci_dict(sum(1 for p in dis_ids if label[p] == "contradicts"),
                         len(dis_ids))

    # direction, on v3-classified supersedes pairs
    dir_rows = []
    for pid in sup_ids:
        if label[pid] != "supersedes":
            continue
        r1 = by_arm[("direction", 0)].get(pid)
        if r1 is None:
            continue
        dir_rows.append({"pair_id": pid, "truth": pairs[pid]["direction_truth"],
                         "observed": r1["label"], "p": max(r1["probs"].values()),
                         "correct": r1["label"] == pairs[pid]["direction_truth"]})
    direction = ci_dict(sum(1 for d in dir_rows if d["correct"]), len(dir_rows)) \
        if dir_rows else None

    # paired baseline on the corrected pairs
    baseline = {}
    for pid in ("sup_d2", "sup_f1"):
        v2 = by_arm[("v2", 0)].get(pid, {}).get("label")
        baseline[pid] = {"v2": v2, "v3": label[pid],
                         "gold": pairs[pid]["gold"]}

    # regression view on the 21 verbatim gold members
    gold_hit = ci_dict(sum(1 for p in gold_members if label[p] == pairs[p]["gold"]),
                       len(gold_members))
    gold_misses = [{"pair_id": p, "gold": pairs[p]["gold"], "observed": label[p]}
                   for p in gold_members if label[p] != pairs[p]["gold"]]

    # stability + per-family recall
    labels_by_pair = defaultdict(set)
    for run in range(3):
        for pid, r in by_arm[("v3", run)].items():
            labels_by_pair[pid].add(r["label"] if r["parse"] else "PARSE_ERROR")
    unstable = [p for p, ls in labels_by_pair.items() if len(ls) > 1]
    families = defaultdict(lambda: [0, 0])
    for pid in sup_ids:
        families[pairs[pid]["family"]][1] += 1
        families[pairs[pid]["family"]][0] += label[pid] == "supersedes"

    result = {
        "schema": "supersedes_002_score_v1",
        "n_pairs": len(pairs),
        "gates": {
            "S2-H1_supersedes_recall>=0.85": {
                "metric": sup_rec, "pass": bool(sup_rec["n"] and sup_rec["rate"] >= 0.85)},
            "S2-H2_zero_supersedes_as_contradicts": {
                "metric": {"k": len(sup_as_contra), "n": len(sup_ids)},
                "pairs": sup_as_contra, "pass": len(sup_as_contra) == 0},
            "S2-H3_zero_distractor_as_supersedes": {
                "metric": {"k": len(dis_as_sup), "n": len(dis_ids)},
                "pairs": dis_as_sup, "pass": len(dis_as_sup) == 0},
            "S2-H4_zero_control_as_supersedes": {
                "metric": {"k": len(ctl_as_sup), "n": len(ctl_ids)},
                "pairs": ctl_as_sup, "pass": len(ctl_as_sup) == 0},
        },
        "supersedes_recall": sup_rec,
        "distractor_contradicts_recall": dis_recall,
        "per_family_recall": {k: f"{v[0]}/{v[1]}" for k, v in sorted(families.items())},
        "direction_question": {"metric": direction, "detail": dir_rows},
        "corrected_pairs_paired_baseline": baseline,
        "gold_member_regression": {"metric": gold_hit, "misses": gold_misses},
        "supersedes_set_labels": {p: label[p] for p in sup_ids},
        "distractor_set_labels": {p: label[p] for p in dis_ids},
        "stability": {"unstable_pairs": unstable,
                      "flip_rate": round(len(unstable) / len(labels_by_pair), 4)},
        "parse_failures_run1": sum(1 for r in by_arm[("v3", 0)].values()
                                   if not r["parse"]),
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    for name, gate in result["gates"].items():
        print(f"{name}: {'PASS' if gate['pass'] else 'FAIL'} {gate['metric']}")
    print(f"per-family recall: {result['per_family_recall']}")
    print(f"gold-member regression (21 verbatim): {gold_hit['k']}/{gold_hit['n']}"
          f"  misses: {gold_misses}")
    print(f"corrected pairs paired baseline: {baseline}")
    if direction:
        print(f"direction: {direction['k']}/{direction['n']} = {direction['rate']}")
    print(f"stability: {len(unstable)}/{len(labels_by_pair)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

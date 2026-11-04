"""Threshold sensitivity sweep — offline re-analysis of frozen run data.

Zero model calls. Two questions:

1. edges_v1 (117 gold pairs, run 1, single-question): how does the edge
   proposal threshold T trade proposal precision against review load? The
   frozen policy uses T = 0.80 (policy v2.3).
2. supersedes_003 (43 pairs, run 1): how does the cascade recovery threshold
   T_yes trade supersedes recall against the risk of repairing a real
   conflict? The frozen rule uses T_yes = 0.80.

Writes results/threshold-sweep.json; the numbers feed the results.md section.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELATIONAL = ("supports", "contradicts", "supersedes")
T_VALUES = (0.50, 0.55, 0.60, 0.70, 0.80, 0.90)
BAND_FLOOR = 0.50  # frozen review-band floor (supersedes_003 protocol)


def load(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def sweep_edge(run1: list) -> list:
    rows = []
    for t in T_VALUES:
        proposed, review, none_decided = [], [], []
        for r in run1:
            label = r["label"]
            p = max(r["probs"].values())
            if label == "unrelated" or p < BAND_FLOOR:
                none_decided.append(r)
            elif p >= t:
                proposed.append(r)
            else:
                review.append(r)
        wrong_proposals = [r for r in proposed if r["gold"] != r["label"]]
        missed = [r for r in none_decided if r["gold"] != "unrelated"]
        per_class = {}
        for gold in (*RELATIONAL, "unrelated"):
            golds = [r for r in run1 if r["gold"] == gold]
            if gold == "unrelated":
                hit = sum(1 for r in golds if r["label"] == "unrelated")
            else:
                hit = sum(1 for r in proposed
                          if r["gold"] == gold and r["label"] == gold)
            per_class[gold] = {"decided_correct": hit, "n": len(golds)}
        rows.append({
            "threshold": t,
            "proposed": len(proposed),
            "proposal_precision": (round(1 - len(wrong_proposals) / len(proposed), 4)
                                   if proposed else None),
            "wrong_proposals": [{"pair_id": r["pair_id"], "gold": r["gold"],
                                 "pred": r["label"], "p": max(r["probs"].values())}
                                for r in wrong_proposals],
            "review_load": round(len(review) / len(run1), 4),
            "decided_none": len(none_decided),
            "missed_edges": [{"pair_id": r["pair_id"], "gold": r["gold"]}
                             for r in missed],
            "per_class_decided_correct": per_class,
        })
    return rows


def sweep_cascade(rows: list) -> list:
    pairs = {json.loads(l)["pair_id"]: json.loads(l)
             for l in (ROOT.parent / "supersedes_003" / "pairs.jsonl")
             .read_text().splitlines() if l.strip()}
    edge1 = {r["pair_id"]: r for r in rows if r["question"] == "edge" and r["run"] == 0}
    rep1 = {r["pair_id"]: r for r in rows
            if r["question"] == "replacement" and r["run"] == 0}
    sup_ids = [p for p in pairs if pairs[p]["stratum"] == "supersedes"]
    dis_ids = [p for p in pairs if pairs[p]["stratum"] == "distractor"]

    out = []
    for t in T_VALUES:
        recovered, repaired, band = [], [], []
        for pid, edge in edge1.items():
            if edge["label"] != "contradicts":
                continue
            rep = rep1.get(pid)
            p_yes = rep["probs"]["yes"] if rep else None
            if p_yes is None:
                continue
            final_sup = p_yes >= t
            if final_sup:
                (recovered if pairs[pid]["gold"] == "supersedes"
                 else repaired).append({"pair_id": pid, "p_yes": p_yes})
            elif p_yes >= BAND_FLOOR:
                band.append({"pair_id": pid, "p_yes": p_yes,
                             "gold": pairs[pid]["gold"]})
        direct = sum(1 for p in sup_ids if edge1[p]["label"] == "supersedes")
        recall = (direct + len(recovered)) / len(sup_ids)
        # safety margin: closest true replacement vs closest real conflict
        yes_sup = [rep1[p]["probs"]["yes"] for p in sup_ids if p in rep1]
        yes_dis = [rep1[p]["probs"]["yes"] for p in dis_ids if p in rep1]
        out.append({
            "threshold": t,
            "supersedes_recall": {"k": direct + len(recovered), "n": len(sup_ids),
                                  "rate": round(recall, 4)},
            "recovered": recovered,
            "repaired_real_conflicts": repaired,
            "review_band": band,
            "margin": {"min_p_yes_true_replacement": round(min(yes_sup), 3) if yes_sup else None,
                       "max_p_yes_real_conflict": round(max(yes_dis), 3) if yes_dis else None},
        })
    return out


def main() -> int:
    run1 = [r for r in load(ROOT / "results" / "runs.jsonl")
            if r["run"] == 0 and r["in_gold"]]
    cascade_rows = load(ROOT.parent / "supersedes_003" / "results" / "runs.jsonl")

    edge_sweep = sweep_edge(run1)
    cascade_sweep = sweep_cascade(cascade_rows)

    result = {
        "schema": "threshold_sweep_v1",
        "note": "offline re-analysis of frozen run data; zero model calls",
        "edge_proposal_threshold": edge_sweep,
        "cascade_recovery_threshold": cascade_sweep,
    }
    out = ROOT / "results" / "threshold-sweep.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print("== edge proposal threshold (117 gold pairs, run 1) ==")
    print(f"{'T':>5} {'proposed':>9} {'precision':>10} {'review%':>8} {'missed':>7}")
    for row in edge_sweep:
        print(f"{row['threshold']:>5} {row['proposed']:>9} "
              f"{str(row['proposal_precision']):>10} "
              f"{row['review_load']*100:>7.1f}% "
              f"{len(row['missed_edges']):>7}")
    print("\n== cascade recovery threshold (supersedes_003, run 1) ==")
    print(f"{'T':>5} {'recall':>8} {'repaired':>9} {'band':>5}  margin")
    for row in cascade_sweep:
        m = row["margin"]
        print(f"{row['threshold']:>5} "
              f"{row['supersedes_recall']['k']}/{row['supersedes_recall']['n']:>3} "
              f"{len(row['repaired_real_conflicts']):>9} "
              f"{len(row['review_band']):>5}  "
              f"min_yes(true)={m['min_p_yes_true_replacement']} "
              f"max_yes(conflict)={m['max_p_yes_real_conflict']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

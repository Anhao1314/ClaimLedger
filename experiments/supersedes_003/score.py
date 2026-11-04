"""supersedes_003 scoring: the frozen cascade decision rule, applied per run.

    edge argmax != contradicts          -> that label
    edge argmax == contradicts:
        replacement p_yes >= 0.80       -> supersedes (cascade-recovered)
        0.50 <= p_yes < 0.80            -> contradicts (review band)
        p_yes < 0.50                    -> contradicts

    python experiments/supersedes_003/score.py
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREV = ROOT.parent / "supersedes_002"


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


def final_label(edge_label: str, rep: dict | None) -> tuple:
    """Returns (label, band) where band describes the cascade path."""
    if edge_label != "contradicts" or rep is None:
        return edge_label, "single-question"
    p_yes = float(rep["probs"]["yes"])
    if p_yes >= 0.80:
        return "supersedes", "cascade-recovered"
    if p_yes >= 0.50:
        return "contradicts", "review-band"
    return "contradicts", "conflict-stands"


def main() -> int:
    rows = [json.loads(line) for line in
            (ROOT / "results" / "runs.jsonl").read_text().splitlines()
            if line.strip()]
    pairs = {json.loads(l)["pair_id"]: json.loads(l)
             for l in (ROOT / "pairs.jsonl").read_text().splitlines()
             if l.strip()}

    by_q = defaultdict(dict)   # (question, run) -> pair_id -> row
    for row in rows:
        by_q[(row["question"], row["run"])][row["pair_id"]] = row

    def cascade(run: int) -> dict:
        out = {}
        for pid, edge in by_q[("edge", run)].items():
            rep = by_q[("replacement", run)].get(pid)
            label, band = final_label(edge["label"], rep)
            out[pid] = {"label": label, "band": band,
                        "edge_label": edge["label"],
                        "p_yes": (float(rep["probs"]["yes"])
                                  if rep else None)}
        return out

    primary = cascade(0)
    runs_all = {run: cascade(run) for run in range(3)}

    sup_ids = [p for p in pairs if pairs[p]["stratum"] == "supersedes"]
    dis_ids = [p for p in pairs if pairs[p]["stratum"] == "distractor"]
    ctl_ids = [p for p in pairs if pairs[p]["stratum"] == "control"]

    # ---- gates -----------------------------------------------------------
    sup_decided = ci_dict(sum(1 for p in sup_ids
                              if primary[p]["label"] == "supersedes"),
                          len(sup_ids))
    repaired = [p for p in dis_ids if primary[p]["label"] == "supersedes"]
    ctl_sup = [p for p in ctl_ids if primary[p]["label"] == "supersedes"]

    # latent risk telemetry: distractor p_yes even below threshold
    dis_yes = [{"pair_id": p, "p_yes": primary[p]["p_yes"],
                "band": primary[p]["band"]}
               for p in dis_ids if primary[p]["p_yes"] is not None]
    dis_yes.sort(key=lambda d: -(d["p_yes"] or 0))

    # ---- direction on supersedes-decided pairs ----------------------------
    dir_rows = []
    for pid in sup_ids:
        if primary[pid]["label"] != "supersedes":
            continue
        r1 = by_q[("direction", 0)].get(pid)
        if r1 is None:
            continue
        truth = pairs[pid]["direction_truth"]
        dir_rows.append({"pair_id": pid, "truth": truth,
                         "observed": r1["label"], "p": max(r1["probs"].values()),
                         "correct": r1["label"] == truth})
    direction = ci_dict(sum(1 for d in dir_rows if d["correct"]),
                        len(dir_rows)) if dir_rows else None

    # ---- stability of final labels ----------------------------------------
    labels_by_pair = defaultdict(set)
    for run in range(3):
        for pid, dec in runs_all[run].items():
            labels_by_pair[pid].add(dec["label"] if dec["label"] else "ERR")
    unstable = sorted(p for p, ls in labels_by_pair.items() if len(ls) > 1)

    # ---- gold members by text match ---------------------------------------
    gold_texts = {(g["src_text"], g["dst_text"]) for g in
                  (json.loads(l) for l in
                   (PREV.parent / "edges_gold" / "gold-v1.jsonl")
                   .read_text().splitlines() if l.strip())}
    gold_members = [p for p in pairs
                    if (pairs[p]["src_text"], pairs[p]["dst_text"]) in gold_texts]
    gold_view = [{"pair_id": p, "gold": pairs[p]["gold"],
                  "final": primary[p]["label"], "band": primary[p]["band"]}
                 for p in gold_members if primary[p]["label"] != pairs[p]["gold"]]

    # ---- p_yes calibration on the replacement subset ----------------------
    buckets = {"p_yes>=0.90": [], "0.80-0.89": [], "0.50-0.79": [], "<0.50": []}
    for pid, dec in primary.items():
        if dec["p_yes"] is None:
            continue
        truth_is_replacement = pairs[pid]["gold"] == "supersedes"
        p = dec["p_yes"]
        key = ("p_yes>=0.90" if p >= 0.90 else "0.80-0.89" if p >= 0.80
               else "0.50-0.79" if p >= 0.50 else "<0.50")
        buckets[key].append((p >= 0.80) == truth_is_replacement)
    calibration = {k: ci_dict(sum(v), len(v)) for k, v in buckets.items() if v}

    recovered = [{"pair_id": p, "band": primary[p]["band"],
                  "p_yes": primary[p]["p_yes"]}
                 for p in sup_ids if primary[p]["band"] == "cascade-recovered"]
    still_missed = [{"pair_id": p, "band": primary[p]["band"],
                     "p_yes": primary[p]["p_yes"],
                     "edge": primary[p]["edge_label"]}
                    for p in sup_ids if primary[p]["label"] != "supersedes"]

    result = {
        "schema": "supersedes_003_score_v1",
        "n_pairs": len(pairs),
        "replacement_subset": sum(1 for p in primary
                                  if primary[p]["p_yes"] is not None),
        "gates": {
            "S3-H1_cascade_recall>=0.85": {
                "metric": sup_decided,
                "pass": bool(sup_decided["n"] and sup_decided["rate"] >= 0.85)},
            "S3-H2_zero_distractor_repaired": {
                "metric": {"k": len(repaired), "n": len(dis_ids)},
                "pairs": repaired, "pass": len(repaired) == 0},
            "S3-H3_zero_control_supersedes": {
                "metric": {"k": len(ctl_sup), "n": len(ctl_ids)},
                "pairs": ctl_sup, "pass": len(ctl_sup) == 0},
        },
        "cascade_recall": sup_decided,
        "recovered_pairs": recovered,
        "still_missed": still_missed,
        "distractor_p_yes_telemetry": dis_yes,
        "direction_question": {"metric": direction, "detail": dir_rows},
        "gold_member_view": {"n": len(gold_members), "label_changes": gold_view},
        "p_yes_calibration": calibration,
        "stability": {"unstable_pairs": unstable,
                      "flip_rate": round(len(unstable) / len(labels_by_pair), 4)},
        "primary_labels": {p: {"final": primary[p]["label"],
                               "band": primary[p]["band"]} for p in sorted(pairs)},
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    for name, gate in result["gates"].items():
        print(f"{name}: {'PASS' if gate['pass'] else 'FAIL'} {gate['metric']}")
    print(f"recovered: {recovered}")
    print(f"still missed: {still_missed}")
    print(f"distractor p_yes telemetry: {dis_yes}")
    if direction:
        print(f"direction: {direction['k']}/{direction['n']} = {direction['rate']}")
    print(f"gold members: {len(gold_members)}, label changes: {gold_view}")
    print(f"p_yes calibration: {calibration}")
    print(f"stability: {len(unstable)}/{len(labels_by_pair)} unstable: {unstable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

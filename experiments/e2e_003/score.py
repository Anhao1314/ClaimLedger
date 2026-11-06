"""e2e_003 scoring: the frozen six gates.

    python experiments/e2e_003/score.py

Inherits A/B/C/D results from e2e_002 v8 (no rerun); scores E and F fresh.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "e2e_002"

CONFLICT_IDS = {
    "03_analytics_storage", "04_console_panel", "15_logs_explicit",
    "16_api_removal_explicit", "17_dependencies_explicit",
    "18_flags_explicit", "19_storage_natural", "20_panel_natural",
    "21_logs_natural", "22_api_natural",
}
INHERITED = {"A": (21, 40), "B": (37, 40), "C": (35, 40), "D": (21, 40)}


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
            (ROOT / "results" / "results.jsonl").read_text().splitlines()
            if line.strip()]
    by_arm = defaultdict(dict)  # arm -> (task, run) -> pass
    for r in rows:
        by_arm[r["arm"]][(r["task"], r["run"])] = bool(r["pass"])

    def vista(arm: str) -> tuple:
        # the 40-task v8 set only (probes are a separate stratum, gate H5);
        # run 1 only for the primary metric
        tasks = sorted({t for t, _ in by_arm.get(arm, {})
                        if not (ROOT / "probe_tasks" / t).exists()})
        passes = sum(1 for t in tasks if by_arm[arm].get((t, 1)))
        return passes, len(tasks)

    conflict = {arm: (sum(1 for (t, run) in by_arm.get(arm, {})
                          if run == 1 and t in CONFLICT_IDS
                          and by_arm[arm][(t, run)]),
                      len(CONFLICT_IDS))
                for arm in ("E", "F")}
    probes = sorted(t for t in {t for arm in by_arm for (t, _) in by_arm[arm]}
                    if (ROOT / "probe_tasks" / t).exists())
    probe = {arm: (sum(1 for t in probes if by_arm.get(arm, {}).get((t, 1))),
                   len(probes))
             for arm in ("C", "E", "F")}

    e_pass, e_n = vista("E")
    f_pass, f_n = vista("F")
    e_overall = ci(e_pass, e_n)
    f_overall = ci(f_pass, f_n)
    c_rate = INHERITED["C"][0] / INHERITED["C"][1]

    gates = {
        "E3-H1_E_sane_baseline>=0.65": {
            "metric": e_overall,
            "pass": bool(e_overall["rate"] and e_overall["rate"] >= 0.65)},
        "E3-H2_E_conflict_blind": {
            "metric": ci(*conflict["E"]),
            "vs_C_inherited": {"k": 9, "n": 10},
            "pass": bool(conflict["E"][0] <= 6 and conflict["E"][0] < 9)},
        "E3-H3_F_non_inferior>=0.825": {
            "metric": f_overall,
            "pass": bool(f_overall["rate"] and f_overall["rate"] >= 0.825)},
        "E3-H4_F_conflict_retention>=8/10": {
            "metric": ci(*conflict["F"]),
            "pass": conflict["F"][0] >= 8},
        "E3-H5_probe_F>=5/8_and_C<=3/8": {
            "metric": {arm: ci(*probe[arm]) for arm in ("C", "E", "F")},
            "pass": bool(probe["F"][0] >= 5 and probe["C"][0] <= 3)},
    }
    result = {
        "schema": "e2e_003_score_v1",
        "n_jobs": len(rows),
        "inherit": {"A": "21/40", "B": "37/40", "C": "35/40", "D": "21/40",
                    "note": "e2e_002 v8 run-1 results, frozen, not rerun"},
        "E_overall": e_overall,
        "F_overall": f_overall,
        "conflict": {arm: ci(*conflict[arm]) for arm in ("E", "F")},
        "probe": {arm: ci(*probe[arm]) for arm in ("C", "E", "F")},
        "gates": gates,
        "token_cost": _token_stats(rows),
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")
    print(f"E overall: {e_pass}/{e_n}   F overall: {f_pass}/{f_n}")
    print(f"conflict  E {conflict['E'][0]}/{conflict['E'][1]}"
          f"  F {conflict['F'][0]}/{conflict['F'][1]}  (C inherited 9/10)")
    print(f"probe     C {probe['C'][0]}/{probe['C'][1]}"
          f"  E {probe['E'][0]}/{probe['E'][1]}  F {probe['F'][0]}/{probe['F'][1]}")
    for name, gate in gates.items():
        print(f"{name}: {'PASS' if gate['pass'] else 'FAIL'}")
    print(f"wrote {out}")
    return 0


def _token_stats(rows: list) -> dict:
    out = {}
    for arm in ("E", "F", "C"):
        vals = [r["prompt_tokens"] for r in rows
                if r["arm"] == arm and r.get("prompt_tokens")]
        if vals:
            out[arm] = {"mean_prompt_tokens": round(sum(vals) / len(vals), 1),
                        "n": len(vals)}
    return out


if __name__ == "__main__":
    raise SystemExit(main())
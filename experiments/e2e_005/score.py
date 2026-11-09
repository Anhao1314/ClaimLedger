"""e2e_005 scoring: repair loop gates, paired against inherited e2e_002 baselines.

    python experiments/e2e_005/score.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "e2e_002"


def binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    total = 0.0
    for i in range(k + 1):
        total += math.comb(n, i) / (2 ** n)
    return min(1.0, 2 * total)


def mcnemar(a_pass: dict, b_pass: dict, tasks: list) -> dict:
    b = sum(1 for t in tasks if a_pass.get(t) and not b_pass.get(t))
    c = sum(1 for t in tasks if not a_pass.get(t) and b_pass.get(t))
    p = binom_two_sided(min(b, c), b + c) if (b + c) else 1.0
    return {"a_only": b, "b_only": c, "p": round(p, 4),
            "n_pairs": b + c}


def main() -> int:
    rows = [json.loads(line) for line in
            (ROOT / "results" / "results.jsonl").read_text().splitlines()
            if line.strip()]
    by_arm = {}
    for r in rows:
        by_arm.setdefault(r["arm"], {})[r["task"]] = r
    tasks = sorted(by_arm["R0"])

    inherited = {}
    for line in (BASE / "results" / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("run") == 1 and r["task"] in tasks and r["arm"] in ("A", "C"):
            inherited.setdefault(r["arm"], {})[r["task"]] = bool(r["pass"])

    r0 = {t: bool(by_arm["R0"][t]["final_pass"]) for t in tasks}
    r1 = {t: bool(by_arm["R1"][t]["final_pass"]) for t in tasks}
    a_base = inherited["A"]
    c_base = inherited["C"]

    def rate(d):
        k = sum(d.values())
        return {"k": k, "n": len(d), "rate": round(k / len(d), 4)}

    def mean_iters(arm):
        vals = [by_arm[arm][t]["iterations"] for t in tasks
                if by_arm[arm][t]["final_pass"]]
        return round(sum(vals) / len(vals), 2) if vals else None

    def repaired(arm):
        init_fail = [t for t in tasks if not by_arm[arm][t]["attempts"][0]["pass"]]
        fixed = [t for t in init_fail if by_arm[arm][t]["final_pass"]]
        return {"initial_fail": len(init_fail), "repaired": len(fixed)}

    h1 = mcnemar(r0, a_base, tasks)
    h2 = mcnemar(r1, c_base, tasks)
    delta = sum(r1.values()) - sum(r0.values())

    gates = {
        "E5-H1_repair_beats_oneshot_no_memory": {
            "R0": rate(r0), "A_baseline": rate(a_base), "mcnemar": h1,
            "pass": bool(sum(r0.values()) > sum(a_base.values()) and h1["p"] < 0.05)},
        "E5-H2_repair_not_worse_with_memory": {
            "R1": rate(r1), "C_baseline": rate(c_base), "mcnemar": h2,
            "pass": bool(sum(r1.values()) >= sum(c_base.values()))},
        "E5-H3_memory_adds_value_in_loop": {
            "delta_tasks": delta, "R1": rate(r1), "R0": rate(r0),
            "pass": delta >= 3},
    }
    result = {
        "schema": "e2e_005_score_v1",
        "n_tasks": len(tasks),
        "R0_final": rate(r0), "R1_final": rate(r1),
        "A_baseline": rate(a_base), "C_baseline": rate(c_base),
        "H1": h1, "H2": h2, "delta_R1_minus_R0": delta,
        "repair_view": {"R0": repaired("R0"), "R1": repaired("R1")},
        "mean_iterations_to_pass": {"R0": mean_iters("R0"),
                                    "R1": mean_iters("R1")},
        "first_attempt": {
            arm: rate({t: bool(by_arm[arm][t]["attempts"][0]["pass"])
                       for t in tasks})
            for arm in ("R0", "R1")},
        "gates": gates,
    }
    out = ROOT / "results" / "score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print(f"R0 final: {rate(r0)['k']}/30  |  A baseline: {rate(a_base)['k']}/30"
          f"  (McNemar b={h1['a_only']} c={h1['b_only']} p={h1['p']})")
    print(f"R1 final: {rate(r1)['k']}/30  |  C baseline: {rate(c_base)['k']}/30"
          f"  (McNemar b={h2['a_only']} c={h2['b_only']} p={h2['p']})")
    print(f"delta R1-R0: {delta} tasks")
    print(f"repair: R0 {repaired('R0')}  R1 {repaired('R1')}")
    print(f"mean iters: R0 {mean_iters('R0')}  R1 {mean_iters('R1')}")
    for name, gate in gates.items():
        print(f"{name}: {'PASS' if gate['pass'] else 'FAIL'}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
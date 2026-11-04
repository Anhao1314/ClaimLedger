"""Aggregate e2e_002 results: pass table, strata, Wilson CI, McNemar."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results" / "results.jsonl"
ARMS = ["A", "B", "C", "D"]

STRATA = {
    "constraint": {
        "01_storage_postgres", "02_retry_cap", "07_api_v1_unchanged",
        "08_log_retention", "09_error_code", "10_margin_language",
        "11_key_path", "12_preregister", "13_claim_strength", "14_attribution",
    },
    "conflict_explicit": {
        "03_analytics_storage", "04_console_panel", "15_logs_explicit",
        "16_api_removal_explicit", "17_dependencies_explicit",
        "18_flags_explicit",
    },
    "conflict_natural": {
        "19_storage_natural", "20_panel_natural", "21_logs_natural",
        "22_api_natural",
    },
    "irrelevant": {
        "05_date_parser", "23_slugify", "24_paginate", "25_sha256",
        "26_human_bytes", "27_clamp", "28_chunks", "29_collapse_spaces",
        "30_median", "31_parse_bool",
    },
    "control": {
        "06_control_math", "32_multiply", "33_is_even", "34_reverse",
        "35_max_list", "36_factorial", "37_count_vowels", "38_title_case",
        "39_flatten", "40_dedupe",
    },
}


def load() -> list:
    if not RESULTS.exists():
        raise SystemExit(f"no results: {RESULTS}")
    rows = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def majority(rows: list) -> bool:
    return sum(1 for row in rows if row["pass"]) > len(rows) / 2


def wilson(passes: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    p = passes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar for discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main() -> int:
    rows = load()
    latest = {}
    for row in rows:
        latest[(row["task"], row["arm"], row["run"])] = row
    rows = list(latest.values())
    by_task_arm = defaultdict(list)
    for row in rows:
        by_task_arm[(row["task"], row["arm"])].append(row)
    tasks = sorted({row["task"] for row in rows})
    runs = max((row["run"] for row in rows), default=1)

    table = {}
    for task in tasks:
        table[task] = {}
        for arm in ARMS:
            arm_rows = by_task_arm.get((task, arm), [])
            table[task][arm] = {
                "pass": majority(arm_rows) if arm_rows else None,
                "runs": len(arm_rows),
                "tokens": round(sum((r.get("prompt_tokens") or 0)
                                    + (r.get("completion_tokens") or 0)
                                    for r in arm_rows) / len(arm_rows), 1)
                if arm_rows else None,
            }

    print(f"# e2e_002 results ({len(tasks)} tasks, {runs} run(s)/arm)\n")
    header = "| task | " + " | ".join(ARMS) + " |"
    print(header)
    print("| --- | " + " | ".join("---:" for _ in ARMS) + " |")
    for task in tasks:
        cells = []
        for arm in ARMS:
            value = table[task][arm]["pass"]
            cells.append("—" if value is None else ("PASS" if value else "fail"))
        print(f"| {task} | " + " | ".join(cells) + " |")

    print("\n## Pass rate\n")
    summary = {}
    for arm in ARMS:
        values = [table[task][arm]["pass"] for task in tasks
                  if table[task][arm]["pass"] is not None]
        passes, n = sum(1 for value in values if value), len(values)
        low, high = wilson(passes, n)
        summary[arm] = {"passes": passes, "n": n,
                        "rate": round(passes / n, 3) if n else None,
                        "wilson": [round(low, 3), round(high, 3)]}
        print(f"- {arm}: {passes}/{n} = "
              f"{passes / n:.0%} (95% CI {low:.0%}–{high:.0%})" if n else
              f"- {arm}: no data")

    print("\n## By stratum (task-level majority)\n")
    print("| stratum | n | " + " | ".join(ARMS) + " |")
    print("| --- | ---: | " + " | ".join("---:" for _ in ARMS) + " |")
    strata_out = {}
    for name, ids in STRATA.items():
        selected = [task for task in tasks if task in ids]
        cells = []
        row_out = {"n": len(selected)}
        for arm in ARMS:
            values = [table[task][arm]["pass"] for task in selected
                      if table[task][arm]["pass"] is not None]
            passes = sum(1 for value in values if value)
            row_out[arm] = {"passes": passes, "n": len(values)}
            cells.append(f"{passes}/{len(values)}" if values else "—")
        strata_out[name] = row_out
        print(f"| {name} | {len(selected)} | " + " | ".join(cells) + " |")

    print("\n## Prompt cost (mean prompt tokens per task)\n")
    prompt_means = {}
    for arm in ARMS:
        values = []
        for task in tasks:
            arm_rows = by_task_arm.get((task, arm), [])
            tokens = [r.get("prompt_tokens") for r in arm_rows
                      if r.get("prompt_tokens") is not None]
            if tokens:
                values.append(sum(tokens) / len(tokens))
        prompt_means[arm] = round(sum(values) / len(values), 1) if values else None
        print(f"- {arm}: {prompt_means[arm]}")
    if prompt_means.get("B") and prompt_means.get("C"):
        print(f"- C/B prompt ratio: {prompt_means['C'] / prompt_means['B']:.2f}")

    print("\n## C vs each arm (McNemar, paired by task)\n")
    comparisons = {}
    for other in ("A", "B", "D"):
        b = c = 0
        for task in tasks:
            c_pass = table[task]["C"]["pass"]
            o_pass = table[task][other]["pass"]
            if c_pass is None or o_pass is None:
                continue
            if c_pass and not o_pass:
                b += 1
            elif o_pass and not c_pass:
                c += 1
        p = mcnemar_p(b, c)
        comparisons[f"C_vs_{other}"] = {"C_only": b, other + "_only": c,
                                        "p": round(p, 4)}
        print(f"- C vs {other}: C-only={b}, {other}-only={c}, p={p:.4f}")

    print("\n## Token use per task (prompt + completion, mean)\n")
    print(header)
    print("| --- | " + " | ".join("---:" for _ in ARMS) + " |")
    for task in tasks:
        cells = [str(table[task][arm]["tokens"]) for arm in ARMS]
        print(f"| {task} | " + " | ".join(cells) + " |")

    out = {"tasks": table, "summary": summary, "strata": strata_out,
           "prompt_means": prompt_means, "comparisons": comparisons,
           "runs": runs}
    (ROOT / "results" / "score.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nPilot note: with six tasks and one run this is a harness check, "
          "not evidence. Full run: 40 tasks, 3 runs, same decision rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
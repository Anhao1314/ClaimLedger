#!/usr/bin/env python3
"""premise_001: does swapping the generation model break constraint compliance,
and does the Jev-first delivery path preserve it?

    . ~/.config/claimledger/deepseek.env
    . ~/.config/claimledger/jev.env        # only condition C needs this
    python scripts/premise_eval.py

Conditions (frozen in protocol.json):
  A  deepseek-flash    + constraint written into the prompt
  B  deepseek-v4-pro   + constraint written into the prompt
  C  deepseek-v4-pro   + constraint delivered by the jev_first layer
     (the constraint sits among 5 distractor records; only what the layer
      admits enters the prompt)

Violation is decided by deterministic oracles (regex / date / number checks),
never by an LLM judge.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jev_first import Cache, RecordStore, judge  # noqa: E402

EXP = ROOT / "experiments" / "premise_001"
ENDPOINT = "https://api.deepseek.com/chat/completions"
SYSTEM = "You are a senior engineer. Follow project constraints exactly."
SEEDS = 3
DISTRACTORS = [
    "The team wiki lives at wiki.internal.",
    "Standups are at 09:30 every weekday.",
    "The CI pipeline runs on GitHub Actions.",
    "Code reviews require two approvals.",
    "The staging environment refreshes nightly.",
]


def call(model: str, prompt: str, *, timeout: float = 150.0) -> tuple:
    key = os.environ["DEEPSEEK_API_KEY"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "temperature": 1.0, "max_tokens": 4000,
    }).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    latency_ms = int((time.monotonic() - started) * 1000)
    content = parsed["choices"][0]["message"].get("content") or ""
    return content, parsed.get("usage") or {}, latency_ms


def oracle(task: dict, output: str) -> str:
    """Return 'violation', 'compliant', or 'unverifiable'. Never an LLM."""
    for pattern in task.get("forbid", []):
        if re.search(pattern, output, re.IGNORECASE):
            return "violation"
    for pattern in task.get("require", []):
        if not re.search(pattern, output, re.IGNORECASE):
            return "unverifiable"
    if task.get("date_check"):
        match = re.search(r"DATE:\s*(\d{4}-\d{2}-\d{2})", output)
        if not match:
            return "unverifiable"
        try:
            proposed = date.fromisoformat(match.group(1))
        except ValueError:
            return "unverifiable"
        return "compliant" if proposed.weekday() == 1 else "violation"  # Tuesday
    if task.get("retention_check") is not None:
        match = re.search(r"RETENTION:\s*(\d+)\s+days", output)
        if not match:
            return "unverifiable"
        limit = int(task["retention_check"])
        return "compliant" if int(match.group(1)) <= limit else "violation"
    return "compliant"


def layer_prompt(task_text: str, model: str, tmp: Path) -> tuple:
    """Condition C: the constraint is buried among distractors; only what the
    jev_first layer admits enters the prompt."""
    store = RecordStore(tmp / f"records-{abs(hash(task_text)) % 99999}.jsonl")
    for text in [task_constraint(task_text)] + DISTRACTORS:
        if text is not None:
            store.append(text, "agent")
    records = store.load()
    judgment = judge(task_text, records, budget_bytes=2048,
                     cache=Cache(tmp / "cache.jsonl"), on_error="review")
    admitted = [e.text for e in judgment.admitted]
    bullets = "\n".join(f"- {text}" for text in admitted) or "- (none)"
    prompt = (f"TASK: {task_text}\n\nRelevant project memory you MUST follow:\n"
              f"{bullets}")
    return prompt, judgment


_CONSTRAINTS: dict = {}


def task_constraint(task_text: str) -> str:
    return _CONSTRAINTS[task_text]


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set; source ~/.config/claimledger/deepseek.env first.")
        return 2
    protocol = json.loads((EXP / "protocol.json").read_text(encoding="utf-8"))
    tasks = [json.loads(line) for line in
             (EXP / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    for task in tasks:
        _CONSTRAINTS[task["task"].replace("\\n", "\n")] = task["constraint"]

    conditions = {
        "A": {"model": "deepseek-flash", "layer": False},
        "B": {"model": "deepseek-flash", "layer": True},
    }

    rows = []
    with tempfile.TemporaryDirectory(prefix="premise-") as tmp:
        for cond_name, cond in conditions.items():
            for task in tasks:
                task_text = task["task"].replace("\\n", "\n")
                prompt, judgment = task_text, None
                if cond["layer"]:
                    prompt, judgment = layer_prompt(task_text, cond["model"], Path(tmp))
                    constraint_admitted = any(
                        task["constraint"] == e.text for e in judgment.admitted)
                else:
                    constraint_admitted = True
                full_prompt = (prompt if cond["layer"] else
                               f"{prompt}\n\nProject constraint you MUST follow:\n"
                               f"- {task['constraint']}\n")
                for seed in range(SEEDS):
                    started = time.monotonic()
                    try:
                        output, usage, latency_ms = call(cond["model"], full_prompt)
                        verdict = oracle(task, output)
                    except Exception as exc:
                        output, verdict, latency_ms = "", "error", int((time.monotonic() - started) * 1000)
                        usage = {}
                    rows.append({
                        "condition": cond_name, "model": cond["model"],
                        "task": task["id"], "seed": seed,
                        "verdict": verdict,
                        "constraint_admitted_by_layer": (
                            None if not cond["layer"] else constraint_admitted),
                        "latency_ms": latency_ms,
                        "output_chars": len(output),
                        "output_head": output[:200],
                    })
                    print(f"{cond_name} {task['id']} seed{seed}: {verdict} "
                          f"({latency_ms} ms)")

    def rate(cond, verdict_kind="violation"):
        subset = [r for r in rows if r["condition"] == cond
                  and r["verdict"] in ("violation", "compliant")]
        if not subset:
            return None
        return round(sum(r["verdict"] == verdict_kind for r in subset) / len(subset), 4)

    rates = {cond: {"violation_rate": rate(cond),
                    "n_scoring": len([r for r in rows if r["condition"] == cond
                                      and r["verdict"] in ("violation", "compliant")]),
                    "n_unverifiable": len([r for r in rows if r["condition"] == cond
                                           and r["verdict"] == "unverifiable"]),
                    "n_errors": len([r for r in rows if r["condition"] == cond
                                     and r["verdict"] == "error"])}
             for cond in conditions}
    vA, vB = rates["A"]["violation_rate"], rates["B"]["violation_rate"]
    delivery_preserves = (vA is not None and vB is not None
                          and vB <= vA + 0.05)
    delivery_degrades = (vA is not None and vB is not None
                         and vB >= vA + 0.10)

    result = {
        "schema": "premise_001_results_v1.1",
        "protocol_frozen_at": protocol["frozen_at"],
        "protocol_version": protocol["schema"],
        "n": len(rows),
        "rates": rates,
        "gates": {
            "delivery_preserves (B <= A + 5pp)": delivery_preserves,
            "delivery_degrades (B >= A + 10pp)": delivery_degrades,
            "model_swap_drift": "UNMEASURED - deferred until a second generation model is available",
        },
        "rows": rows,
    }
    (EXP / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")

    print("\n===== premise_001 v1.1 (flash-only) =====")
    for cond, data in rates.items():
        print(f"{cond}: violation {data['violation_rate']}  "
              f"(n={data['n_scoring']}, unverifiable {data['n_unverifiable']}, "
              f"errors {data['n_errors']})")
    print(f"delivery preserves (B <= A + 5pp) : {delivery_preserves}")
    print(f"delivery degrades (B >= A + 10pp) : {delivery_degrades}")
    print("model-swap drift                  : UNMEASURED (deferred)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
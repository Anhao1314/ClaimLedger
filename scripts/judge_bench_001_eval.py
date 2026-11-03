#!/usr/bin/env python3
"""judge_bench_001: is the judge a commodity? Five axes, three judges.

    . ~/.config/claimledger/jev.env
    . ~/.config/claimledger/deepseek.env
    python scripts/judge_bench_001_eval.py

Axes: accuracy / stability (label flips across runs) / calibration (Brier) /
schema reliability (parse failures) / latency. Protocol frozen in
experiments/judge_bench_001/protocol.json — no edits after the first call.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_distiller import jev  # noqa: E402
from jev_first import contracts  # noqa: E402
from scripts.jev_crossmodel import parse_label  # noqa: E402

EXP = ROOT / "experiments" / "judge_bench_001"
PAIRS = ROOT / "experiments" / "relation_002" / "pairs.jsonl"
LABELS = ("contradiction", "complementary", "unrelated")
ENDPOINT = "https://api.deepseek.com/chat/completions"
SYSTEM = ("You judge the relation between two statements. Answer only with a "
          "JSON object containing a probability for each label; the three "
          "probabilities must sum to 1.0.")


def ask_jev(pair: dict, question: dict) -> dict:
    state = f"Statement A: {pair['a']}\nStatement B: {pair['b']}"
    started = time.monotonic()
    try:
        parsed = jev.ask(state, {"relation": question}, consent=True, timeout=90)
    except jev.JevError as exc:
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": str(exc)[:80]}
    latency = int((time.monotonic() - started) * 1000)
    answer = jev.answer(parsed, "relation")
    probs = answer.get("probabilities") or {}
    label = max(probs, key=probs.get) if probs else answer.get("choice")
    ok = label in LABELS and all(isinstance(probs.get(l), (int, float)) for l in LABELS)
    return {"parse": ok, "label": label if ok else None,
            "probs": {l: float(probs.get(l, 0.0)) for l in LABELS} if ok else None,
            "latency_ms": latency, "usage": parsed.get("usage") or {}}


def ask_deepseek(pair: dict, criteria: dict, model: str, temperature: float) -> dict:
    lines = ["Relation criteria:"]
    for label in LABELS:
        lines.append(f"- {label}: {criteria[label]}")
    lines += ["", f"Statement A: {pair['a']}", f"Statement B: {pair['b']}", "",
              "Answer only with JSON: " +
              '{"probabilities": {"contradiction": 0.0, "complementary": 0.0, "unrelated": 0.0}}']
    key = os.environ["DEEPSEEK_API_KEY"]
    body = json.dumps({"model": model,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": "\n".join(lines)}],
                       "temperature": temperature, "max_tokens": 200,
                       "response_format": {"type": "json_object"}}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"parse": False, "label": None, "probs": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": str(exc)[:80]}
    latency = int((time.monotonic() - started) * 1000)
    content = parsed["choices"][0]["message"].get("content") or ""
    try:
        payload = json.loads(content)
        probs = payload.get("probabilities") or {}
        values = {l: float(probs.get(l, 0.0)) for l in LABELS}
        total = sum(values.values())
        if total <= 0 or any(v < 0 for v in values.values()):
            raise ValueError("bad probabilities")
        values = {l: v / total for l, v in values.items()}
        label = max(values, key=values.get)
        return {"parse": True, "label": label, "probs": values,
                "latency_ms": latency, "usage": parsed.get("usage") or {}}
    except (json.JSONDecodeError, ValueError, AttributeError):
        label = parse_label(content)
        ok = label in LABELS
        return {"parse": ok, "label": label if ok else None, "probs": None,
                "latency_ms": latency, "usage": parsed.get("usage") or {}}


def run_batch(judge_name: str, runs: int, temperature: float, pairs: list,
              criteria: dict, question: dict) -> list:
    rows = []
    def one(pair):
        if judge_name == "jev":
            return ask_jev(pair, question)
        return ask_deepseek(pair, criteria, judge_name, temperature)
    for run in range(runs):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(one, pairs))
        elapsed = int((time.monotonic() - started) * 1000)
        for pair, result in zip(pairs, results):
            rows.append({"run": run, "id": pair["id"],
                         "gold": pair["label"], **result})
        print(f"  {judge_name} run {run + 1}/{runs}: {elapsed} ms total")
    return rows


def summarize(judge_name: str, rows: list, pairs: list) -> dict:
    by_run = {}
    for row in rows:
        by_run.setdefault(row["run"], []).append(row)
    accuracies = []
    briers = []
    for run_rows in by_run.values():
        scored = [r for r in run_rows if r["parse"]]
        if not scored:
            continue
        accuracies.append(sum(r["label"] == r["gold"] for r in scored) / len(scored))
        briers.append(statistics.mean(
            (r["probs"]["contradiction"] - (1.0 if r["gold"] == "contradiction" else 0.0)) ** 2
            for r in scored if r["probs"]))
    labels_by_pair = {}
    for row in rows:
        labels_by_pair.setdefault(row["id"], set()).add(row["label"] if row["parse"] else "PARSE_ERROR")
    unstable = sum(1 for labels in labels_by_pair.values() if len(labels) > 1)
    parse_fail = sum(1 for r in rows if not r["parse"])
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
    tokens_in = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in rows)
    tokens_out = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in rows)
    return {
        "judge": judge_name,
        "runs": len(by_run),
        "calls": len(rows),
        "accuracy": {
            "mean": round(statistics.mean(accuracies), 4) if accuracies else None,
            "min": round(min(accuracies), 4) if accuracies else None,
            "max": round(max(accuracies), 4) if accuracies else None,
        },
        "unstable_pairs": {"count": unstable, "rate": round(unstable / len(pairs), 4)},
        "parse_failures": {"count": parse_fail,
                           "rate": round(parse_fail / len(rows), 4) if rows else None},
        "brier": round(statistics.mean(briers), 4) if briers else None,
        "latency_ms": {"median": int(statistics.median(latencies)) if latencies else None},
        "tokens": {"input": tokens_in, "output": tokens_out},
    }


def main() -> int:
    protocol = json.loads((EXP / "protocol.json").read_text(encoding="utf-8"))
    pairs = [json.loads(line) for line in
             PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]
    criteria = contracts.question("relation")["criteria"]
    question = contracts.relation_question()
    if not jev.configured() or not os.environ.get("DEEPSEEK_API_KEY"):
        print("both TYPESAFE_API_KEY and DEEPSEEK_API_KEY are required")
        return 2

    all_rows = {}
    summaries = {}
    print("jev (5 runs)...")
    all_rows["jev"] = run_batch("jev", 5, 0, pairs, criteria, question)
    print("deepseek-flash (5 runs @ t=1.0)...")
    all_rows["deepseek-flash"] = run_batch("deepseek-flash", 5, 1.0, pairs, criteria, question)
    print("deepseek-flash (1 run @ t=0)...")
    all_rows["deepseek-flash-best"] = run_batch("deepseek-flash", 1, 0.0, pairs, criteria, question)
    print("deepseek-v4-pro (3 runs @ t=1.0)...")
    all_rows["deepseek-v4-pro"] = run_batch("deepseek-v4-pro", 3, 1.0, pairs, criteria, question)
    print("deepseek-v4-pro (1 run @ t=0)...")
    all_rows["deepseek-v4-pro-best"] = run_batch("deepseek-v4-pro", 1, 0.0, pairs, criteria, question)

    for name, rows in all_rows.items():
        summaries[name] = summarize(name, rows, pairs)

    jev_s = summaries["jev"]
    commodity = False
    for name in ("deepseek-flash", "deepseek-v4-pro"):
        s = summaries[name]
        if (s["accuracy"]["mean"] is not None and jev_s["accuracy"]["mean"] is not None
                and s["accuracy"]["mean"] >= jev_s["accuracy"]["mean"]
                and s["unstable_pairs"]["rate"] <= jev_s["unstable_pairs"]["rate"]
                and s["parse_failures"]["rate"] <= jev_s["parse_failures"]["rate"]):
            commodity = True

    result = {
        "schema": "judge_bench_001_results_v1",
        "protocol": protocol["schema"],
        "n_pairs": len(pairs),
        "summaries": summaries,
        "gates": {
            "judge_is_commodity": commodity,
            "decision": ("commodity: swap the judge, keep the pipeline"
                         if commodity else
                         "jev has a structural advantage on at least one axis"),
        },
        "rows": {name: rows for name, rows in all_rows.items()},
    }
    (EXP / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")

    print("\n===== judge_bench_001 =====")
    print(f"{'judge':22} {'acc mean':>9} {'range':>15} {'unstable':>9} {'parse fail':>10} {'Brier':>7} {'p50 ms':>7}")
    for name, s in summaries.items():
        acc = s["accuracy"]
        rng = f"{acc['min']:.2f}-{acc['max']:.2f}" if acc["min"] is not None else "-"
        print(f"{name:22} {str(acc['mean']):>9} {rng:>15} "
              f"{s['unstable_pairs']['rate']:>9} {str(s['parse_failures']['rate']):>10} "
              f"{str(s['brier']):>7} {str(s['latency_ms']['median']):>7}")
    print(f"\njudge_is_commodity: {commodity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
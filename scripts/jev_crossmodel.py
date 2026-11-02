#!/usr/bin/env python3
"""Cross-model replay: the same frozen 30 pairs, the same contract question,
judged by a DIFFERENT model family (DeepSeek) instead of Jev.

This is the first real "change the judge model, keep the memory" measurement:
records and question semantics are held fixed; only the model changes.

    . ~/.config/claimledger/deepseek.env
    python scripts/jev_crossmodel.py

Writes experiments/jev_relation_001/crossmodel-<model>.json and compares with
the Jev baseline (results.json) and with the frozen labels.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jev_first import contracts  # noqa: E402

EXP = ROOT / "experiments" / "jev_relation_001"
LABELS = ("contradiction", "complementary", "unrelated")
ENDPOINT = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")

SYSTEM = "You judge the relation between two statements. Answer only with a JSON object, no other text."


def build_user_message(pair: dict, criteria: dict) -> str:
    lines = ["Relation criteria:"]
    for label in LABELS:
        lines.append(f"- {label}: {criteria[label]}")
    lines += ["", f"Statement A: {pair['a']}", f"Statement B: {pair['b']}", "",
              'Which relation holds between A and B? Answer only with JSON: '
              '{"relation": "contradiction" | "complementary" | "unrelated"}']
    return "\n".join(lines)


def parse_label(content: str) -> str:
    try:
        value = json.loads(content).get("relation")
        if value in LABELS:
            return value
    except (json.JSONDecodeError, AttributeError):
        pass
    found = re.findall(r"contradiction|complementary|unrelated", content)
    return found[0] if found else "PARSE_ERROR"


def ask_deepseek(model: str, user_message: str, *, timeout: float = 60.0) -> tuple:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user_message}],
        "temperature": 0, "max_tokens": 200,
        "response_format": {"type": "json_object"},
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
    return parse_label(content), parsed.get("usage") or {}, latency_ms, parsed


def main() -> int:
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set; source ~/.config/claimledger/deepseek.env first.")
        return 2

    contracts.verify_manifest()
    criteria = contracts.question("relation")["criteria"]
    baseline = {row["id"]: row for row in
                json.loads((EXP / "results.json").read_text(encoding="utf-8"))["rows"]}
    pairs = [json.loads(line) for line in
             (EXP / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    rows = []
    for pair in pairs:
        try:
            observed, usage, latency_ms, raw = ask_deepseek(
                model, build_user_message(pair, criteria))
        except Exception as exc:  # transport, HTTP, parse
            rows.append({**pair, "observed": "ERROR", "error": str(exc)[:120]})
            continue
        prior = baseline.get(pair["id"], {}).get("observed")
        rows.append({
            **pair, "observed": observed,
            "jev_observed": prior,
            "agree_with_jev": (observed == prior) if prior not in (None, "ERROR") else None,
            "agree_with_label": observed == pair["label"],
            "usage": usage, "latency_ms": latency_ms,
        })

    scored = [r for r in rows if r["observed"] != "ERROR"]
    comparable = [r for r in scored if r.get("agree_with_jev") is not None]
    agree_jev = sum(r["agree_with_jev"] for r in comparable)
    accuracy = sum(r["agree_with_label"] for r in scored) / len(scored) if scored else None
    confusion = {label: {other: 0 for other in LABELS} for label in LABELS}
    for row in scored:
        confusion[row["label"]][row["observed"]] += 1
    latencies = [r["latency_ms"] for r in scored]
    tokens_in = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in scored)
    tokens_out = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in scored)

    result = {
        "schema": "jev_crossmodel_v1",
        "judge_model": model,
        "baseline_models": sorted({r.get("model") for r in baseline.values()
                                   if r.get("model")}),
        "question_source": "contracts/questions.v1.json (relation criteria, verbatim)",
        "n": len(rows), "scored": len(scored), "errors": len(rows) - len(scored),
        "cross_model": {
            "comparable": len(comparable),
            "agreement_with_jev": round(agree_jev / len(comparable), 4) if comparable else None,
            "disagreements": [[r["id"], r["jev_observed"], r["observed"]]
                              for r in comparable if not r["agree_with_jev"]],
        },
        "accuracy_vs_frozen_labels": accuracy,
        "confusion": confusion,
        "latency_ms": {"median": int(statistics.median(latencies)) if latencies else None,
                       "max": max(latencies) if latencies else None},
        "tokens": {"input": tokens_in, "output": tokens_out},
        "rows": rows,
    }
    out = EXP / f"crossmodel-{model}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'id':4} {'label':14} {'jev':14} {'deepseek':14} {'=jev':5} {'=label':6} {'ms':>6}")
    print("-" * 66)
    for row in rows:
        print(f"{row['id']:4} {row['label']:14} {str(row.get('jev_observed')):14} "
              f"{row['observed']:14} "
              f"{str(row.get('agree_with_jev')):5} "
              f"{str(row.get('agree_with_label')):6} "
              f"{row.get('latency_ms', ''):>6}")
    print("-" * 66)
    if comparable:
        print(f"agreement with Jev        : {agree_jev}/{len(comparable)} "
              f"({agree_jev / len(comparable):.0%})")
    if accuracy is not None:
        print(f"accuracy vs frozen labels : {accuracy:.0%}  ({len(scored)} scored)")
    for label in LABELS:
        row = confusion[label]
        print(f"  {label:14} -> {row}")
    if latencies:
        print(f"latency: median {int(statistics.median(latencies))} ms, max {max(latencies)} ms")
    print(f"tokens: in {tokens_in}, out {tokens_out}   errors: {len(rows) - len(scored)}")
    for row in result["cross_model"]["disagreements"]:
        print(f"DISAGREEMENT {row[0]}: jev={row[1]} deepseek={row[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
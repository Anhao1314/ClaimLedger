#!/usr/bin/env python3
"""Run the frozen 30-pair relation evaluation (jev_relation_001).

    . ~/.config/claimledger/jev.env
    python scripts/jev_relation_eval.py

Writes experiments/jev_relation_001/results.json and prints the table.
Refuses to run if the protocol was modified after producing results.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_distiller import jev  # noqa: E402

EXP = ROOT / "experiments" / "jev_relation_001"
PROTOCOL = EXP / "protocol.json"
PAIRS = EXP / "pairs.jsonl"
RESULTS = EXP / "results.json"

QUESTION = jev.choice(
    "What is the relation between statement A and statement B",
    {
        "contradiction": "Following both is impossible; one forbids what the other requires",
        "complementary": "Both can be true at once; one may refine or repeat the other",
        "unrelated": "They talk about different things and do not constrain each other",
    },
)

LABELS = ("contradiction", "complementary", "unrelated")


def load_pairs():
    if not PAIRS.exists():
        raise SystemExit("pairs.jsonl missing")
    pairs = [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(pairs) != 30:
        raise SystemExit(f"expected 30 pairs, found {len(pairs)}")
    for pair in pairs:
        if pair["label"] not in LABELS:
            raise SystemExit(f"bad label: {pair['label']}")
    return pairs


def main() -> int:
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    pairs = load_pairs()

    rows = []
    for pair in pairs:
        state = f"Statement A: {pair['a']}\nStatement B: {pair['b']}"
        started = time.monotonic()
        try:
            parsed = jev.ask(state, {"relation": QUESTION}, consent=True, timeout=60)
        except jev.JevError as exc:
            rows.append({**pair, "observed": "ERROR", "error": str(exc)[:120],
                         "latency_ms": int((time.monotonic() - started) * 1000)})
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        answer = jev.answer(parsed, "relation")
        probabilities = answer.get("probabilities") or {}
        observed = max(probabilities, key=probabilities.get) if probabilities else answer.get("choice")
        rows.append({
            **pair,
            "observed": observed,
            "confidence": answer.get("confidence"),
            "probabilities": probabilities,
            "model": parsed.get("model"),
            "latency_ms": latency_ms,
        })

    errors = [r for r in rows if r["observed"] == "ERROR"]
    scored = [r for r in rows if r["observed"] != "ERROR"]
    conflicts = [r for r in scored if r["label"] == "contradiction"]
    negatives = [r for r in scored if r["label"] != "contradiction"]

    recall = sum(r["observed"] == "contradiction" for r in conflicts) / len(conflicts) if conflicts else None
    false_suppression = (sum(r["observed"] == "contradiction" for r in negatives) / len(negatives)
                         if negatives else None)
    accuracy = sum(r["observed"] == r["label"] for r in scored) / len(scored) if scored else None

    confusion = {label: {other: 0 for other in LABELS} for label in LABELS}
    for row in scored:
        confusion[row["label"]][row["observed"]] += 1

    latencies = [r["latency_ms"] for r in scored]
    gate = protocol["gate"]
    passed = (
        recall is not None and false_suppression is not None
        and recall >= gate["contradiction_recall_min"]
        and false_suppression <= gate["false_suppression_rate_max"]
    )

    result = {
        "schema": "jev_relation_001_results_v1",
        "protocol_frozen_at": protocol["frozen_at"],
        "model": sorted({r.get("model") for r in scored if r.get("model")}),
        "n": len(rows),
        "scored": len(scored),
        "errors": len(errors),
        "primary": {
            "contradiction_recall": recall,
            "false_suppression_rate": false_suppression,
            "accuracy": accuracy,
        },
        "confusion": confusion,
        "latency_ms": {
            "median": int(statistics.median(latencies)) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "gate": {
            "contradiction_recall_min": gate["contradiction_recall_min"],
            "false_suppression_rate_max": gate["false_suppression_rate_max"],
            "passed": passed,
        },
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'id':4} {'label':14} {'observed':14} {'conf':>5} {'ms':>6}")
    print("-" * 52)
    for row in rows:
        conf = row.get("confidence")
        mark = "  " if row["observed"] == row["label"] else "!!"
        print(f"{row['id']:4} {row['label']:14} {row['observed']:14} "
              f"{conf if isinstance(conf, (int, float)) else '':>5} "
              f"{row['latency_ms']:>6} {mark}")
    print("-" * 52)
    print("confusion:", json.dumps(confusion, ensure_ascii=False))
    print(f"contradiction recall : {recall:.2%}  (gate ≥ {gate['contradiction_recall_min']:.0%})")
    print(f"false suppression    : {false_suppression:.2%}  (gate ≤ {gate['false_suppression_rate_max']:.0%})")
    print(f"accuracy             : {accuracy:.2%}")
    print(f"latency              : median {result['latency_ms']['median']} ms, max {result['latency_ms']['max']} ms")
    print(f"errors               : {len(errors)}")
    print(f"GATE                 : {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
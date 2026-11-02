#!/usr/bin/env python3
"""Replay: same contract question set, different model, diff the judgments.

This is the smallest form of "change the model, keep the memory": the records
(the 30 frozen pairs), the question set (contracts/questions.v1.json), and the
decision rule (argmax) are held fixed; only the model changes.

    . ~/.config/claimledger/jev.env
    python scripts/jev_replay.py jev-preview

Writes experiments/jev_relation_001/replay-<model>.json and prints the diff
against results.json (the jev-latest baseline).
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
from jev_first import contracts  # noqa: E402

EXP = ROOT / "experiments" / "jev_relation_001"
LABELS = ("contradiction", "complementary", "unrelated")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: jev_replay.py <model>   e.g. jev-preview")
        return 2
    model = sys.argv[1]
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2

    contracts.verify_manifest()
    question = contracts.relation_question()
    baseline_rows = {row["id"]: row for row in
                     json.loads((EXP / "results.json").read_text(encoding="utf-8"))["rows"]}
    baseline_model = sorted({r.get("model") for r in baseline_rows.values() if r.get("model")})
    pairs = [json.loads(line) for line in
             (EXP / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    rows = []
    for pair in pairs:
        state = f"Statement A: {pair['a']}\nStatement B: {pair['b']}"
        started = time.monotonic()
        try:
            parsed = jev.ask(state, {"relation": question}, consent=True,
                             timeout=60, model=model)
        except jev.JevError as exc:
            rows.append({**pair, "observed": "ERROR", "error": str(exc)[:120],
                         "latency_ms": int((time.monotonic() - started) * 1000)})
            continue
        answer = jev.answer(parsed, "relation")
        probabilities = answer.get("probabilities") or {}
        observed = max(probabilities, key=probabilities.get) if probabilities else answer.get("choice")
        prior = baseline_rows.get(pair["id"], {})
        prior_p = (prior.get("probabilities") or {}).get("contradiction")
        rows.append({
            **pair, "observed": observed,
            "confidence": answer.get("confidence"),
            "probabilities": probabilities,
            "prior_observed": prior.get("observed"),
            "prior_p_contradiction": prior_p,
            "p_delta_contradiction": (
                round(probabilities.get("contradiction", 0.0) - prior_p, 4)
                if isinstance(prior_p, (int, float)) else None),
            "model": parsed.get("model"),
            "latency_ms": int((time.monotonic() - started) * 1000),
        })

    scored = [r for r in rows if r["observed"] != "ERROR"]
    comparable = [r for r in scored
                  if r.get("prior_observed") not in (None, "ERROR")]
    agree = [r for r in comparable if r["observed"] == r["prior_observed"]]
    flips = [r for r in comparable if r["observed"] != r["prior_observed"]]
    deltas = [abs(r["p_delta_contradiction"]) for r in comparable
              if r["p_delta_contradiction"] is not None]
    latencies = [r["latency_ms"] for r in scored]
    models = sorted({r.get("model") for r in scored if r.get("model")})

    result = {
        "schema": "jev_replay_v1",
        "requested_model": model,
        "served_models": models,
        "baseline_models": baseline_model,
        "question_source": "contracts/questions.v1.json (relation)",
        "n": len(rows), "scored": len(scored), "errors": len(rows) - len(scored),
        "label_agreement": {
            "comparable": len(comparable),
            "agree": len(agree),
            "differ": len(flips),
            "rate": round(len(agree) / len(comparable), 4) if comparable else None,
        },
        "contradiction_probability": {
            "mean_abs_delta": round(statistics.mean(deltas), 4) if deltas else None,
            "max_abs_delta": round(max(deltas), 4) if deltas else None,
        },
        "latency_ms": {
            "median": int(statistics.median(latencies)) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "rows": rows,
    }
    out = EXP / f"replay-{model}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"requested : {model}")
    print(f"served    : {models}   baseline: {baseline_model}")
    print(f"{'id':4} {'label':14} {'replay':14} {'baseline':14} {'conf':>5} {'d_p(con)':>9}")
    print("-" * 66)
    for row in rows:
        conf = row.get("confidence")
        delta = row.get("p_delta_contradiction")
        mark = "  " if row["observed"] == row.get("prior_observed") else "!!"
        print(f"{row['id']:4} {row['label']:14} {row['observed']:14} "
              f"{str(row.get('prior_observed')):14} "
              f"{conf if isinstance(conf, (int, float)) else '':>5} "
              f"{delta if delta is not None else '':>9} {mark}")
    print("-" * 66)
    if comparable:
        print(f"label agreement : {len(agree)}/{len(comparable)} "
              f"({len(agree) / len(comparable):.0%})   flips: {len(flips)}")
    if deltas:
        print(f"|Δ p(contradiction)| : mean {statistics.mean(deltas):.3f}  max {max(deltas):.3f}")
    if latencies:
        print(f"latency         : median {int(statistics.median(latencies))} ms, "
              f"max {max(latencies)} ms")
    print(f"transport errors: {len(rows) - len(scored)}")
    if flips:
        print("FLIPPED PAIRS:")
        for row in flips:
            print(f"  {row['id']}  {row['prior_observed']} -> {row['observed']}  ({row['label']})")
    if not models:
        print("no served model recorded")
    elif set(models) == set(baseline_model):
        print("NOTE: served version identical to baseline - this measured sampling "
              "stability, not a model swap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
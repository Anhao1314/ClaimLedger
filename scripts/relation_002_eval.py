#!/usr/bin/env python3
"""relation_002: three-method comparison on the adversarial 60-pair benchmark.

    . ~/.config/claimledger/jev.env
    . ~/.config/claimledger/deepseek.env
    python scripts/relation_002_eval.py

Methods: lexical baseline (offline, deterministic), Jev (contract question,
full probability map), deepseek-flash (same criteria, JSON answer). Reports
per-tier accuracy, S-group consistency, the discriminating gate, and the
margin ablation sweep over Jev probability maps.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_distiller import jev  # noqa: E402
from jev_first import contracts  # noqa: E402
from scripts.jev_crossmodel import parse_label  # noqa: E402

EXP = ROOT / "experiments" / "relation_002"
LABELS = ("contradiction", "complementary", "unrelated")
ENDPOINT = "https://api.deepseek.com/chat/completions"
SYSTEM = "You judge the relation between two statements. Answer only with a JSON object, no other text."
STOP = frozenset("the a an for to of in on and or is are be at by from as that this it its with".split())


def tokens(text: str) -> set:
    import re
    return {t for t in re.findall(r"\w+", text.lower()) if t not in STOP and len(t) > 1}


def lexical_baseline(pair: dict) -> str:
    """Deliberately dumb deterministic baseline. Proves the benchmark bites."""
    ta, tb = tokens(pair["a"]), tokens(pair["b"])
    smaller = min(len(ta), len(tb)) or 1
    overlap = len(ta & tb) / smaller
    if overlap >= 0.5:
        return "complementary"
    if overlap >= 0.15:
        return "contradiction"
    return "unrelated"


def ask_jev(pair: dict, question: dict) -> tuple:
    state = f"Statement A: {pair['a']}\nStatement B: {pair['b']}"
    parsed = jev.ask(state, {"relation": question}, consent=True, timeout=60)
    answer = jev.answer(parsed, "relation")
    probabilities = answer.get("probabilities") or {}
    observed = max(probabilities, key=probabilities.get) if probabilities else answer.get("choice")
    return observed, probabilities, parsed.get("model"), int(0), parsed.get("usage") or {}


def ask_deepseek(pair: dict, criteria: dict, model: str) -> tuple:
    lines = ["Relation criteria:"]
    for label in LABELS:
        lines.append(f"- {label}: {criteria[label]}")
    lines += ["", f"Statement A: {pair['a']}", f"Statement B: {pair['b']}", "",
              'Which relation holds? Answer only with JSON: {"relation": "...", "confidence": 0.0}']
    key = os.environ["DEEPSEEK_API_KEY"]
    body = json.dumps({"model": model,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": "\n".join(lines)}],
                       "temperature": 0, "max_tokens": 200,
                       "response_format": {"type": "json_object"}}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=90) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    latency = int((time.monotonic() - started) * 1000)
    content = parsed["choices"][0]["message"].get("content") or ""
    observed = parse_label(content)
    return observed, {}, latency, parsed


def margin_of(probabilities: dict) -> float | None:
    values = sorted((float(v) for v in probabilities.values()
                     if isinstance(v, (int, float))), reverse=True)
    return None if len(values) < 2 else values[0] - values[1]


def main() -> int:
    protocol = json.loads((EXP / "protocol.json").read_text(encoding="utf-8"))
    pairs = [json.loads(line) for line in
             (EXP / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    criteria = contracts.question("relation")["criteria"]
    relation_q = contracts.relation_question()

    have_jev = jev.configured()
    have_ds = bool(os.environ.get("DEEPSEEK_API_KEY"))

    rows = []
    for pair in pairs:
        row = {**pair, "lexical": lexical_baseline(pair),
               "jev": None, "jev_probs": None, "deepseek": None, "ds_conf": None}
        if have_jev:
            try:
                observed, probs, served, _, _ = ask_jev(pair, relation_q)
                row["jev"], row["jev_probs"], row["jev_served"] = observed, probs, served
            except jev.JevError as exc:
                row["jev"], row["jev_error"] = "ERROR", str(exc)[:80]
        if have_ds:
            try:
                observed, _, _, _ = ask_deepseek(pair, criteria, os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"))
                row["deepseek"] = observed
            except Exception as exc:
                row["deepseek"], row["ds_error"] = "ERROR", str(exc)[:80]
        rows.append(row)
        print(f"{pair['id']:4} {pair['tier']:3} {pair['label']:14} "
              f"lex={row['lexical']:14} jev={str(row['jev']):14} ds={str(row['deepseek']):14}")

    tiers = ("E", "HN", "HP", "S")
    methods = ("lexical", "jev", "deepseek")
    per_tier = {m: {t: None for t in tiers} for m in methods}
    overall = {m: None for m in methods}
    for m in methods:
        scored = [r for r in rows if r[m] not in (None, "ERROR")]
        if scored:
            overall[m] = round(sum(r[m] == r["label"] for r in scored) / len(scored), 4)
        for t in tiers:
            subset = [r for r in scored if r["tier"] == t]
            if subset:
                per_tier[m][t] = round(sum(r[m] == r["label"] for r in subset) / len(subset), 4)

    # S-group consistency: per group, all three variants must match gold
    groups: dict = {}
    for r in rows:
        if r["tier"] != "S" or r[r["jev"] and "jev" or "jev"] is None:
            continue
        groups.setdefault(r["group"], []).append(r)
    s_consistency = {}
    for m in ("jev", "deepseek"):
        if not have_jev and m == "jev":
            continue
        if not have_ds and m == "deepseek":
            continue
        clean_groups = []
        for gname, grows in groups.items():
            if all(r[m] not in (None, "ERROR") for r in grows):
                clean_groups.append(all(r[m] == r["label"] for r in grows))
        s_consistency[m] = (round(sum(clean_groups) / len(clean_groups), 4)
                            if clean_groups else None)

    # margin ablation over Jev probability maps
    ablation = {}
    scored_jev = [r for r in rows if r.get("jev_probs")]
    for delta in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
        confirmed = [r for r in scored_jev
                     if r["jev"] == "contradiction"
                     and (margin_of(r["jev_probs"]) or 0.0) >= delta]
        tp = sum(r["label"] == "contradiction" for r in confirmed)
        fp = len(confirmed) - tp
        fn = sum(1 for r in scored_jev if r["label"] == "contradiction"
                 and not (r["jev"] == "contradiction"
                          and (margin_of(r["jev_probs"]) or 0.0) >= delta))
        precision = round(tp / len(confirmed), 4) if confirmed else None
        recall = round(tp / (tp + fn), 4) if (tp + fn) else None
        ablation[str(delta)] = {"confirmed": len(confirmed), "tp": tp, "fp": fp,
                                "precision": precision, "recall": recall}
    gate = protocol["gates"]
    lex_hp = per_tier["lexical"]["HP"]
    model_hp = max((per_tier[m]["HP"] or 0) for m in ("jev", "deepseek")
                   if per_tier[m]["HP"] is not None), 
    discriminating = (lex_hp is not None and lex_hp <= gate["lexical_hp_max"]
                      and model_hp[0] >= 0.70)

    result = {
        "schema": "relation_002_results_v1",
        "protocol": protocol["schema"],
        "models": {"jev": sorted({r.get("jev_served") for r in rows if r.get("jev_served")}),
                   "deepseek": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")},
        "overall": overall, "per_tier": per_tier,
        "s_group_consistency": s_consistency,
        "margin_ablation_jev": ablation,
        "gates": {"discriminating": discriminating,
                  "models_overall_min": gate["models_overall_min"],
                  "easy_tier_min": gate["easy_tier_min"],
                  "hard_positive_min": gate["hard_positive_min"]},
        "rows": [{k: v for k, v in r.items() if k != "jev_probs"} for r in rows],
        "_jev_prob_maps": {r["id"]: r["jev_probs"] for r in rows if r.get("jev_probs")},
    }
    (EXP / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")

    print("\n===== relation_002 =====")
    print(f"{'tier':5} {'lexical':>9} {'jev':>7} {'deepseek':>9}")
    for t in tiers:
        print(f"{t:5} {str(per_tier['lexical'][t]):>9} {str(per_tier['jev'][t]):>7} "
              f"{str(per_tier['deepseek'][t]):>9}")
    print(f"{'ALL':5} {str(overall['lexical']):>9} {str(overall['jev']):>7} "
          f"{str(overall['deepseek']):>9}")
    print("S-group consistency:", s_consistency)
    print(f"discriminating gate (lex HP <= 0.50 AND model HP >= 0.70): {discriminating}")
    print("margin ablation (Jev):")
    for delta, data in ablation.items():
        print(f"  δ={delta}: confirmed {data['confirmed']:2}  P={data['precision']}  R={data['recall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
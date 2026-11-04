#!/usr/bin/env python3
"""Consistency check: re-run the 30 frozen pairs using the *contract* question.

If the contract is the product, then the validated result must be reproducible
from the contract file alone — not from a question hard-coded in a script.

    . ~/.config/claimledger/jev.env
    python scripts/jev_contract_check.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_distiller import jev  # noqa: E402
from jev_first import contracts  # noqa: E402

EXP = ROOT / "experiments" / "jev_relation_001"


def main() -> int:
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2

    status = contracts.verify_manifest()
    print("contracts:", status)
    question = contracts.relation_question()
    print(f"question source: contracts/{contracts.QUESTIONS_FILE.name} (relation)\n")

    prior = {row["id"]: row for row in
             json.loads((EXP / "results.json").read_text(encoding="utf-8"))["rows"]}
    pairs = [json.loads(line) for line in
             (EXP / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    matched = differed = errored = 0
    details = []
    for pair in pairs:
        state = f"Statement A: {pair['a']}\nStatement B: {pair['b']}"
        started = time.monotonic()
        try:
            parsed = jev.ask(state, {"relation": question}, consent=True, timeout=60)
        except jev.JevError as exc:
            errored += 1
            details.append((pair["id"], pair["label"], "ERROR", "-", "-", str(exc)[:40]))
            continue
        answer = jev.answer(parsed, "relation")
        probabilities = answer.get("probabilities") or {}
        observed = max(probabilities, key=probabilities.get) if probabilities else answer.get("choice")
        prior_row = prior.get(pair["id"], {})
        prior_observed = prior_row.get("observed")
        if prior_observed in (None, "ERROR"):
            details.append((pair["id"], pair["label"], observed,
                            str(prior_observed), answer.get("confidence"), "prior n/a"))
            continue
        if observed == prior_observed:
            matched += 1
            mark = "  "
        else:
            differed += 1
            mark = "!!"
        details.append((pair["id"], pair["label"], observed, str(prior_observed),
                        answer.get("confidence"), mark))

    print(f"{'id':4} {'label':14} {'contract':14} {'prior':14} {'conf':>5}")
    print("-" * 58)
    for row in details:
        print(f"{row[0]:4} {row[1]:14} {row[2]:14} {row[3]:14} {row[4] if row[4] != '-' else '':>5} {row[5]}")
    print("-" * 58)
    comparable = matched + differed
    print(f"label agreement with results.json : {matched}/{comparable} comparable pairs")
    print(f"differs                           : {differed}")
    print(f"transport errors this run         : {errored}")
    consistent = comparable > 0 and differed == 0
    print(f"CONTRACT CONSISTENCY              : {'CONFIRMED' if consistent else 'BROKEN'}")
    return 0 if consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
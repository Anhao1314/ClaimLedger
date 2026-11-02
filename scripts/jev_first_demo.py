#!/usr/bin/env python3
"""End-to-end demo of the Jev-first decision layer.

One request, four claims, one typed decision, one appended log line.
Status is deliberately NOT shown to the model: it must judge from content.

    . ~/.config/claimledger/jev.env
    python scripts/jev_first_demo.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_distiller import jev  # noqa: E402
from jev_first import decide, log  # noqa: E402

TASK = "Write a storage adapter for the analytics service."

CLAIMS = [
    {"claim_id": "clm_pg", "text": "All storage must use PostgreSQL.", "status": "现行"},
    {"claim_id": "clm_compat", "text": "SQLite is deprecated for this service.", "status": "现行"},
    {"claim_id": "clm_analytics", "text": "PostgreSQL is banned for the analytics service.", "status": "现行"},
    {"claim_id": "clm_staging", "text": "Use SQLite for staging.", "status": "已过期"},
]


def main() -> int:
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2

    decision = decide(TASK, CLAIMS, budget_bytes=1024)

    print(f"task      : {decision.task}")
    print(f"model     : {decision.model}   policy: {decision.policy['version']}")
    print(f"latency   : {decision.latency_ms} ms   tokens: {decision.usage}")
    print(f"contradict: {decision.contradiction:.2f}   governing: {decision.governing}"
          f" ({decision.governing_confidence})")
    print()
    print(f"{'claim':14} {'p(applies)':>10} {'p(holds)':>9} {'score':>6}  {'action':7} {'in':3}")
    print("-" * 60)
    for entry in sorted(decision.entries, key=lambda e: e.score, reverse=True):
        print(f"{entry.claim_id:14} {entry.p_applies:>10.2f} {entry.p_holds:>9.2f} "
              f"{entry.score:>6.2f}  {entry.action:7} {'yes' if entry.included else 'no':3}")
    print("-" * 60)
    print(f"bytes {decision.used_bytes}/{decision.budget_bytes}   omitted {decision.omitted}")

    with tempfile.TemporaryDirectory(prefix="jev-first-") as tmp:
        path = Path(tmp) / "decisions.jsonl"
        log.append(path, decision)
        row = log.read(path)[0]
        print(f"\nlogged one decision ({len(row['entries'])} entries) -> {path.name}")

    return 0 if decision.governing == "clm_analytics" else 1


if __name__ == "__main__":
    raise SystemExit(main())
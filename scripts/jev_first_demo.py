#!/usr/bin/env python3
"""End-to-end demo of the Jev-first core:

    record store (hash chain)
      → stage 1: one admit choice per record, judged alone
      → stage 2: pairwise relation localizes conflicts (validated question)
      → stage 3: governing
      → sealed judgment log

The scenario contains a genuine conflict (all-PostgreSQL vs banned-for-
analytics). Watch what happens to "SQLite is deprecated": it is NOT dragged
into the conflict, because localization is per-pair, not global.

    . ~/.config/claimledger/jev.env
    python scripts/jev_first_demo.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_distiller import jev  # noqa: E402
from jev_first import Cache, RecordStore, judge, log  # noqa: E402

TASK = "Write a storage adapter for the analytics service."

RECORDS = [
    ("All storage must use PostgreSQL.", "agent"),
    ("SQLite is deprecated for this service.", "agent"),
    ("PostgreSQL is banned for the analytics service.", "human"),
    ("Use SQLite for staging.", "agent"),
]


def print_judgment(judgment, label):
    print(f"--- {label} ---")
    print(f"model {judgment.model}   qset {judgment.question_set_version}   "
          f"cached {judgment.cached}   requests {judgment.requests}   "
          f"latency {judgment.latency_ms} ms")
    print(f"conflicts {judgment.conflicts or 'none'}   "
          f"pair_checks {judgment.pair_checks}   governing {judgment.governing}")
    print(f"{'record':18} {'action':8} {'p(admit)':>9} {'gov':4} {'cf':4} {'in':3}")
    print("-" * 54)
    for entry in sorted(judgment.entries, key=lambda e: (e.p_admit or 0), reverse=True):
        print(f"{entry.record_id:18} {entry.action:8} "
              f"{entry.p_admit if entry.p_admit is not None else '':>9} "
              f"{'yes' if entry.governing else '':4} "
              f"{'yes' if entry.conflicted else '':4} "
              f"{'yes' if entry.included else 'no':3}")
    print(f"bytes {judgment.used_bytes}/{judgment.budget_bytes}   "
          f"omitted {judgment.omitted}\n")


def main() -> int:
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2

    with tempfile.TemporaryDirectory(prefix="jev-first-") as tmp:
        base = Path(tmp)
        store = RecordStore(base / "records.jsonl")
        for text, source in RECORDS:
            store.append(text, source)
        records = store.load()
        print(f"records: {len(records)} (chain verified, no stored status)\n")

        cache = Cache(base / "cache.jsonl")
        cold = judge(TASK, records, budget_bytes=1024, cache=cache)
        started = time.monotonic()
        warm = judge(TASK, records, budget_bytes=1024, cache=cache)
        warm_served_ms = int((time.monotonic() - started) * 1000)
        print_judgment(cold, "cold (fresh requests)")
        print_judgment(warm, f"warm (cache hit, served in {warm_served_ms} ms)")

        sealed = [log.append_judgment(base / "judgments.jsonl", j.to_dict())
                  for j in (cold, warm)]
        count = log.verify(base / "judgments.jsonl")
        print(f"log: {count} judgments sealed, chain verified")

        checks = (
            warm.cached
            and count == 2
            and len(cold.conflicts) >= 1
            and all(e.conflicted for e in cold.entries
                    if e.record_id in cold.conflicts[0])
            and not any(e.conflicted for e in cold.entries
                        if e.record_id not in
                        [rid for pair in cold.conflicts for rid in pair])
        )
        return 0 if checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
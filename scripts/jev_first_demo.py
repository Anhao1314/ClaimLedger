#!/usr/bin/env python3
"""End-to-end demo of the Jev-first core:

    record store (hash chain) → judge (cache miss then hit) → sealed log

Status is never stored and never shown to the model. The second call is served
from the cache in microseconds; the log is verified at the end.

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
          f"cached {judgment.cached}   latency {judgment.latency_ms} ms")
    print(f"contradiction {judgment.contradiction:.2f}   governing {judgment.governing}")
    print(f"{'record':18} {'action':8} {'p(admit)':>9} {'gov':4} {'in':3}")
    print("-" * 50)
    for entry in sorted(judgment.entries, key=lambda e: (e.p_admit or 0), reverse=True):
        print(f"{entry.record_id:18} {entry.action:8} "
              f"{entry.p_admit if entry.p_admit is not None else '':>9} "
              f"{'yes' if entry.governing else '':4} "
              f"{'yes' if entry.included else 'no':3}")
    print(f"bytes {judgment.used_bytes}/{judgment.budget_bytes}   omitted {judgment.omitted}\n")


def explain(judgment):
    if judgment.contradiction >= judgment.policy["contradiction_review_at"]:
        print("NOTE: the candidate set contains an unresolved contradiction, so every "
              "record is review by design — a human must resolve the conflict before "
              "anything is admitted. Localizing the conflict (per-pair relation) is "
              "the next build item.\n")


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
        print_judgment(cold, "cold (one Jev request)")
        explain(cold)
        print_judgment(warm, f"warm (cache hit, served in {warm_served_ms} ms, "
                             f"original latency preserved)")

        sealed = [log.append_judgment(base / "judgments.jsonl", j.to_dict())
                  for j in (cold, warm)]
        count = log.verify(base / "judgments.jsonl")
        print(f"log: {count} judgments sealed, chain verified")
        print(f"last hash: {sealed[-1]['judgment_hash'][:24]}…")

        same = all(a.to_dict()["entries"] == b.to_dict()["entries"]
                   for a, b in zip([cold], [warm]))
        print(f"cache served an identical decision: {same}")
        return 0 if (warm.cached and count == 2 and same) else 1


if __name__ == "__main__":
    raise SystemExit(main())
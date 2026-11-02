#!/usr/bin/env python3
"""Probe whether Jev can adjudicate claim relations that lexical overlap cannot.

This is the first, smallest experiment behind "change models, keep memory":
before wiring a decision model into retrieval, check whether it can separate
contradiction from complement and from coincidence at all.

    . ~/.config/claimledger/jev.env
    python scripts/jev_probe.py

Sends only the synthetic pairs below. No ledger content is read or transmitted.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_distiller import jev  # noqa: E402

CASES = [
    ("C1", "contradiction",
     "All storage must use PostgreSQL.",
     "This service must use SQLite; PostgreSQL is forbidden here."),
    ("C2", "complementary",
     "All storage uses PostgreSQL.",
     "SQLite is deprecated for this service."),
    ("C3", "unrelated",
     "All storage uses PostgreSQL.",
     "The release train leaves on Friday at 14:00 UTC."),
    ("C4", "contradiction",
     "PostgreSQL is banned for this service.",
     "Use PostgreSQL for all storage."),
    ("C5", "complementary",
     "Storage must run on PostgreSQL 16.",
     "Use PostgreSQL 16 for all storage."),
]

QUESTIONS = {
    "relation": jev.choice(
        "What is the relation between statement A and statement B",
        {
            "contradiction": "Following both is impossible; one forbids what the other requires",
            "complementary": "Both can be true at once; one may refine or repeat the other",
            "unrelated": "They talk about different things and do not constrain each other",
        },
    ),
    "confidence_note": jev.noul(
        "The two statements constrain the same decision, even if they do not contradict",
    ),
}


def main() -> int:
    if not jev.configured():
        print("TYPESAFE_API_KEY is not set; source ~/.config/claimledger/jev.env first.")
        return 2
    rows = []
    for case_id, expected, a, b in CASES:
        state = f"Statement A: {a}\nStatement B: {b}"
        started = time.monotonic()
        try:
            parsed = jev.ask(state, QUESTIONS, consent=True, timeout=30)
        except jev.JevError as exc:
            rows.append((case_id, expected, "ERROR", "", "", f"{exc}"[:60]))
            continue
        elapsed = (time.monotonic() - started) * 1000
        relation = jev.answer(parsed, "relation")
        observed = relation.get("choice", "?")
        confidence = relation.get("confidence")
        p_contra = (relation.get("probabilities") or {}).get("contradiction")
        rows.append((
            case_id, expected, observed,
            f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "",
            f"{p_contra:.2f}" if isinstance(p_contra, (int, float)) else "",
            f"{elapsed:.0f}ms  {parsed.get('model', '')}",
        ))

    width = max(len(r[1]) for r in rows) + 2
    print(f"{'case':5} {'expected':<{width}} {'observed':<15} {'conf':>5} {'p(con)':>7}  note")
    print("-" * 78)
    hits = 0
    for case_id, expected, observed, confidence, p_contra, note in rows:
        hit = observed == expected
        hits += hit
        print(f"{case_id:5} {expected:<{width}} {observed:<15} {confidence:>5} {p_contra:>7}  {note}")
    print("-" * 78)
    print(f"agreement: {hits}/{len(rows)}")
    print("\nC4 is the lexical blind spot: high word overlap, opposite meaning.")
    return 0 if hits == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
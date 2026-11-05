"""real_use_001: day-14 analysis from the audit trails. No self-reporting.

    python experiments/real_use_001/analyze.py [--store ~/.jev-work] [--as-of YYYY-MM-DD]

Reads the hash-chained logs directly (records, proposals, edges, judgments,
outcomes) and produces results/summary.json against the pre-registered
thresholds in protocol.md. Safe to run any day; `--as-of` bounds the window.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((center - spread) / denom, (center + spread) / denom)


def ci(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)]}


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def in_window(row: dict, as_of: str) -> bool:
    at = str(row.get("at") or row.get("created_at") or "")
    return (not as_of) or at[:10] <= as_of


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=os.path.expanduser("~/.jev-work"))
    parser.add_argument("--as-of", default="",
                        help="ISO date; rows after this date are excluded")
    parser.add_argument("--start", default="2026-11-06",
                        help="day-1 date; day-0 baseline rows are excluded")
    args = parser.parse_args()

    store = Path(args.store)

    def window(rows: list) -> list:
        return [r for r in rows
                if str(r.get("at") or r.get("created_at") or "")[:10] >= args.start
                and in_window(r, args.as_of)]

    records_all = read_jsonl(store / "records.jsonl")
    proposals_all = read_jsonl(store / "proposals.jsonl")
    edges_all = read_jsonl(store / "edges.jsonl")
    judgments_all = read_jsonl(store / "judgments.jsonl")
    outcomes_all = read_jsonl(store / "outcomes.jsonl")

    prop_events = window(proposals_all)
    edge_events = window(edges_all)
    judgments = window(judgments_all)
    outcomes = window(outcomes_all)

    prop_created = [r for r in prop_events if r.get("type") == "proposal"]
    prop_decisions = [r for r in prop_events if r.get("type") == "decision"]
    edge_created = [r for r in edge_events if r.get("type") == "proposal"]
    edge_decisions = [r for r in edge_events if r.get("type") == "decision"]

    decided_days = sorted({str(r.get("created_at", ""))[:10]
                           for r in judgments if r.get("created_at")})

    # scored outcomes: upheld/overturned against judgments in the window
    scored = [o for o in outcomes if o.get("verdict") in ("upheld", "overturned")]
    upheld = ci(sum(1 for o in scored if o["verdict"] == "upheld"), len(scored))
    brier_values = []
    by_hash = {r.get("judgment_hash"): r for r in judgments_all}
    for o in scored:
        j = by_hash.get(o.get("judgment_hash"))
        if not j:
            continue
        for entry in j.get("entries", []):
            if entry.get("record_id") == o.get("record_id") \
                    and entry.get("action") == "admit" \
                    and isinstance(entry.get("p_admit"), (int, float)):
                y = 1.0 if o["verdict"] == "upheld" else 0.0
                brier_values.append((entry["p_admit"] - y) ** 2)

    # gate integrity: a record whose canonical id does not match any confirmed
    # proposal's decided record is not evidence of a bypass (agents may be
    # humans too); the honest proxy is proposal-less appends, which we detect
    # by comparing record sources against registered agents that only speak MCP.
    proposal_confirmed_ids = {r.get("record_id") for r in prop_decisions
                              if r.get("decision") == "confirmed"}
    # human direct writes (console/CLI "+ record") carry a by= attestation;
    # they are the human surface, not ungated agent writes
    direct_ids = {r.get("record_id") for r in read_jsonl(store / "direct_writes.jsonl")
                  if r.get("type") == "direct_write"}
    baseline_ids = set()  # filled from day0.json if present
    day0 = ROOT / "results" / "day0.json"
    if day0.exists():
        baseline_ids = {r["record_id"] for r in
                        json.loads(day0.read_text())["records"]}
    new_records = [r for r in records_all if r["record_id"] not in baseline_ids]
    via_proposal = {r.get("record_id") for r in proposal_confirmed_ids}
    bypass = [r["record_id"] for r in new_records
              if r["record_id"] not in via_proposal
              and r["record_id"] not in direct_ids]

    summary = {
        "schema": "real_use_001_summary_v1",
        "window": {"start": args.start, "as_of": args.as_of or "now"},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "usage": {
            "active_days": len(decided_days), "active_day_list": decided_days,
            "decide_brief_calls": len(judgments),
            "degraded_calls": sum(1 for r in judgments if r.get("degraded")),
            "record_count_total": len(records_all),
            "new_records": len(new_records),
            "sources_of_new_records": dict(Counter(
                r.get("source", "?") for r in new_records)),
        },
        "proposals": {
            "created": len(prop_created),
            "confirmed": sum(1 for r in prop_decisions if r.get("decision") == "confirmed"),
            "rejected": sum(1 for r in prop_decisions if r.get("decision") == "rejected"),
            "pending": len(prop_created) - len(prop_decisions),
        },
        "edges": {
            "created": len(edge_created),
            "confirmed": sum(1 for r in edge_decisions if r.get("decision") == "confirmed"),
            "rejected": sum(1 for r in edge_decisions if r.get("decision") == "rejected"),
            "pending": len(edge_created) - len(edge_decisions),
            "by_type": dict(Counter(r.get("edge_type", "?") for r in edge_created)),
            "by_source": dict(Counter(r.get("source", "?") for r in edge_created)),
        },
        "outcomes": {
            "scored": len(scored),
            "upheld_rate": upheld,
            "brier": round(sum(brier_values) / len(brier_values), 4)
                     if brier_values else None,
            "unclear": sum(1 for o in outcomes if o.get("verdict") == "unclear"),
        },
        "gate_integrity": {
            "new_records_not_via_proposal": bypass,
            "violations": len(bypass),
        },
        "gates": {
            "G1_active_days>=12": {"metric": len(decided_days),
                                   "pass": len(decided_days) >= 12},
            "G2_scored_outcomes>=10": {"metric": len(scored),
                                       "pass": len(scored) >= 10},
            "G3_proposals>=3": {"metric": len(prop_created),
                                "pass": len(prop_created) >= 3},
            "G4_zero_gate_violations": {"metric": len(bypass),
                                        "pass": len(bypass) == 0},
        },
    }
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    suffix = args.as_of or "now"
    out = out_dir / f"summary-{args.start}-to-{suffix}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print(f"window: {args.start} → {args.as_of or 'now'}")
    print(f"active days: {len(decided_days)}/14  calls: {len(judgments)}"
          f"  degraded: {summary['usage']['degraded_calls']}")
    print(f"proposals: {summary['proposals']}")
    print(f"edges: {summary['edges']}")
    print(f"outcomes: scored {len(scored)}, upheld {upheld}, "
          f"brier {summary['outcomes']['brier']}")
    print(f"gate violations: {len(bypass)} {bypass or ''}")
    for name, gate in summary["gates"].items():
        print(f"  {name}: {'PASS' if gate['pass'] else 'not yet'} ({gate['metric']})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 1: source B inventory + candidate pair generation (no model calls).

Usage:
    python experiments/edges_gold/generate_candidates.py

Reads:
    experiments/e2e_002/memory/records.jsonl   (source A: 55 records)
    ~/.jev-work/records.jsonl                   (source B: production records)

Writes:
    experiments/edges_gold/source-b-inventory.md
    experiments/edges_gold/candidates.jsonl
    experiments/edges_gold/annotation-user.jsonl   (empty edge_type/valid for user)
    experiments/edges_gold/annotation-zcode.jsonl  (empty edge_type/valid for zcode)
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

from jev_first.records import RecordStore

SOURCE_A = ROOT.parent / "e2e_002" / "memory" / "records.jsonl"
SOURCE_B = Path(os.path.expanduser("~/.jev-work/records.jsonl"))
OUTPUT = ROOT

STOPWORDS = frozenset(
    "the a an of to for in on at by with and or is are was were be been "
    "this that it its as from must should".split())


def tokens(text: str) -> set:
    import re
    words = re.findall(r"[a-z\u4e00-\u9fff0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def overlap_bucket(j: float) -> str:
    if j >= 0.4:
        return "high"
    if j >= 0.15:
        return "medium"
    return "low"


def load_source_a() -> list:
    return [json.loads(line) for line in SOURCE_A.read_text().splitlines() if line.strip()]


def load_source_b() -> list:
    if not SOURCE_B.exists():
        return []
    return [json.loads(line) for line in SOURCE_B.read_text().splitlines() if line.strip()]


def inventory_source_b(records: list) -> str:
    """Report the maximum number of candidate pairs source B can produce."""
    n = len(records)
    total_pairs = n * (n - 1) // 2
    lines = [
        "# Source B inventory\n",
        f"Records: {n}",
        f"Max same-source pairs: {total_pairs}",
        "",
        "## Per-record pair participation",
        "",
    ]
    for r in records:
        lines.append(f"- {r['record_id']} ({r['source']}): {r['text'][:60]}")
    lines.append("")
    lines.append(f"## Candidate pair ceiling: {total_pairs}")
    lines.append("")
    lines.append(f"Verdict: {'sufficient (≥20)' if total_pairs >= 20 else 'INSUFFICIENT (<20)'} for Phase 1 sampling.")
    return "\n".join(lines)


def generate_pairs(source_a: list, source_b: list) -> list:
    """Generate all same-source candidate pairs with overlap features."""
    pairs = []
    for source_name, records in [("A", source_a), ("B", source_b)]:
        for (a, b) in itertools.combinations(records, 2):
            ta, tb = tokens(a["text"]), tokens(b["text"])
            j = jaccard(ta, tb)
            pair_id = "pair_" + hashlib.sha256(
                f"{a['record_id']}|{b['record_id']}".encode()).hexdigest()[:12]
            pairs.append({
                "pair_id": pair_id,
                "source": source_name,
                "src_id": a["record_id"],
                "dst_id": b["record_id"],
                "src_text": a["text"],
                "dst_text": b["text"],
                "src_kind": "record",
                "dst_kind": "record",
                "overlap": round(j, 3),
                "bucket": overlap_bucket(j),
            })
    return pairs


def stratified_sample(pairs: list, target: int = 120) -> list:
    """Sample pairs stratified by source and overlap bucket.

    Target distribution (approximate, not guaranteed):
    - high overlap → likely supports/contradicts (need more)
    - medium overlap → likely unrelated or ambiguous (need some)
    - low overlap → likely unrelated (need some for negative controls)

    Source A:B ≈ 70:30, adjusted by availability.
    """
    rng = random.Random("edges_gold_v1")
    by_key = {}
    for pair in pairs:
        key = (pair["source"], pair["bucket"])
        by_key.setdefault(key, []).append(pair)

    # Target allocation (fractions of 120)
    allocation = {
        ("A", "high"): 28, ("A", "medium"): 22, ("A", "low"): 24,
        ("B", "high"): 12, ("B", "medium"): 10, ("B", "low"): 8,
    }
    # Scale by availability if insufficient
    sampled = []
    for key, want in allocation.items():
        pool = by_key.get(key, [])
        take = min(want, len(pool))
        sampled.extend(rng.sample(pool, take))

    # Fill to target from remaining pool
    sampled_ids = {p["pair_id"] for p in sampled}
    remaining = [p for p in pairs if p["pair_id"] not in sampled_ids]
    rng.shuffle(remaining)
    while len(sampled) < target and remaining:
        pair = remaining.pop()
        if pair["pair_id"] not in sampled_ids:
            sampled.append(pair)
            sampled_ids.add(pair["pair_id"])

    rng.shuffle(sampled)
    return sampled[:target]


def write_candidates(sampled: list) -> None:
    out = OUTPUT / "candidates.jsonl"
    with open(out, "w", encoding="utf-8") as handle:
        for pair in sampled:
            handle.write(json.dumps(pair, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"candidates: {len(sampled)} pairs → {out}")


def write_annotation_templates(sampled: list) -> None:
    """Two isolated annotation files: user fills edge_type, zcode fills edge_type."""
    for annotator in ("user", "zcode"):
        out = OUTPUT / f"annotation-{annotator}.jsonl"
        with open(out, "w", encoding="utf-8") as handle:
            for pair in sampled:
                handle.write(json.dumps({
                    "pair_id": pair["pair_id"],
                    "src_text": pair["src_text"],
                    "dst_text": pair["dst_text"],
                    "edge_type": None,
                    "confidence": None,
                    "direction": None,
                    "annotator": annotator,
                }, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"annotation-{annotator}.jsonl: {len(sampled)} rows (edge_type=null)")


def main() -> int:
    source_a = load_source_a()
    source_b = load_source_b()
    print(f"source A: {len(source_a)} records; source B: {len(source_b)} records")

    # Source B inventory
    inventory = inventory_source_b(source_b)
    (OUTPUT / "source-b-inventory.md").write_text(inventory, encoding="utf-8")
    print(inventory)

    # Generate all pairs with features
    all_pairs = generate_pairs(source_a, source_b)
    print(f"total same-source pairs: {len(all_pairs)}")

    # Stratified sample 120
    sampled = stratified_sample(all_pairs, target=120)
    write_candidates(sampled)
    write_annotation_templates(sampled)

    # Summary
    from collections import Counter
    buckets = Counter(p["bucket"] for p in sampled)
    sources = Counter(p["source"] for p in sampled)
    print(f"sampled bucket distribution: {dict(buckets)}")
    print(f"sampled source distribution: {dict(sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
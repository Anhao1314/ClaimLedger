"""Phase 1 dual-model agreement analysis: Cohen's kappa, confusion matrix,
constructed-pair probe, contested pool.

Usage:
    python experiments/edges_gold/analyze_agreement.py

Reads:
    experiments/edges_gold/annotation-zcode.jsonl
    experiments/edges_gold/annotation-deepseek.jsonl

Writes:
    experiments/edges_gold/agreement-summary.json
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TYPES = ["supports", "contradicts", "supersedes", "unrelated", "abstain"]

# Constructed ground truth: labels guaranteed by corpus design, independent of
# any annotator. 5 designed conflict pairs + 6 sampled cross-pairs of the four
# delta=0.2 margin wording variants.
CONSTRUCTED = {
    "pair_8fe8ccfbc0bb": "contradicts",  # no new panels vs must add proposals panel
    "pair_e6d5116f9868": "contradicts",  # flags off vs on
    "pair_4a9416ef6ff9": "contradicts",  # structured logs must vs must not
    "pair_4ebc907a632a": "contradicts",  # PG everywhere vs banned for analytics
    "pair_bd1025c2b932": "contradicts",  # API v1 remain vs removed in Q4
    "pair_a31daffc0f9b": "supports",     # margin M3 vs M1
    "pair_a4a7b5558e6a": "supports",     # margin M4 vs M2
    "pair_eddb9143c324": "supports",     # margin M3 vs M2
    "pair_6c3b84eae77a": "supports",     # margin M4 vs M1
    "pair_32846ee0c743": "supports",     # margin M1 vs M2
    "pair_87bc9503f98a": "supports",     # margin M4 vs M3
}

# Type-B disagreements: ontology boundary disputes (both sides see a relation,
# they disagree on which one). Type-A: one side sees no relation at all.
BOUNDARY = {frozenset(("supports", "supersedes")),
            frozenset(("contradicts", "supersedes"))}


def load(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["pair_id"]: r for r in rows}


def main() -> int:
    zc = load(ROOT / "annotation-zcode.jsonl")
    ds = load(ROOT / "annotation-deepseek.jsonl")
    assert set(zc) == set(ds) and len(zc) == 120, "annotator pair sets differ"

    ids = sorted(zc)
    z_labels = [zc[i]["edge_type"] for i in ids]
    d_labels = [ds[i]["edge_type"] for i in ids]

    # --- Cohen's kappa (unweighted, 5 classes) ---
    n = len(ids)
    zc_counts = Counter(z_labels)
    ds_counts = Counter(d_labels)
    po = sum(1 for z, d in zip(z_labels, d_labels) if z == d) / n
    pe = sum(zc_counts[t] * ds_counts[t] for t in TYPES) / (n * n)
    kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")

    # --- confusion matrix: rows = zcode, cols = deepseek ---
    conf = {z: {d: 0 for d in TYPES} for z in TYPES}
    for z, d in zip(z_labels, d_labels):
        conf[z][d] += 1

    # --- constructed-pair probe ---
    probe_ds = {i: ds[i]["edge_type"] for i in CONSTRUCTED}
    probe_zc = {i: zc[i]["edge_type"] for i in CONSTRUCTED}
    probe_ds_ok = sum(1 for i, t in CONSTRUCTED.items() if probe_ds[i] == t)
    probe_zc_ok = sum(1 for i, t in CONSTRUCTED.items() if probe_zc[i] == t)
    probe_miss = [{"pair_id": i, "expected": t, "deepseek": probe_ds[i],
                   "zcode": probe_zc[i]}
                  for i, t in CONSTRUCTED.items()
                  if probe_ds[i] != t or probe_zc[i] != t]

    # --- contested pool ---
    contested = []
    for i in ids:
        z, d = zc[i]["edge_type"], ds[i]["edge_type"]
        if z != d:
            kind = "B" if frozenset((z, d)) in BOUNDARY else "A"
            contested.append({
                "pair_id": i,
                "zcode": z, "zcode_conf": zc[i]["confidence"],
                "deepseek": d, "deepseek_conf": ds[i]["confidence"],
                "type": kind,
            })

    contested_type_a = [c for c in contested if c["type"] == "A"]
    contested_type_b = [c for c in contested if c["type"] == "B"]

    summary = {
        "version": "edges_gold_v1_agreement_v1",
        "n_pairs": n,
        "zcode_distribution": dict(zc_counts),
        "deepseek_distribution": dict(ds_counts),
        "raw_agreement": round(po, 4),
        "expected_agreement": round(pe, 4),
        "cohens_kappa": round(kappa, 4),
        "confusion_matrix": conf,
        "constructed_probe": {
            "n": len(CONSTRUCTED),
            "deepseek_correct": probe_ds_ok,
            "zcode_correct": probe_zc_ok,
            "misses": probe_miss,
        },
        "contested": {
            "n": len(contested),
            "type_a_semantic": len(contested_type_a),
            "type_b_boundary": len(contested_type_b),
            "pairs": contested,
        },
        "gold_rule": "agreement pairs become gold; contested pairs are excluded "
                     "from the frozen gold and reported separately",
    }
    out = ROOT / "agreement-summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")

    print(f"raw agreement: {po:.3f}   expected: {pe:.3f}   kappa: {kappa:.3f}")
    print(f"constructed probe: deepseek {probe_ds_ok}/{len(CONSTRUCTED)}"
          f"   zcode {probe_zc_ok}/{len(CONSTRUCTED)}")
    for m in probe_miss:
        print(f"  miss {m['pair_id']}: expected {m['expected']}, "
              f"deepseek={m['deepseek']}, zcode={m['zcode']}")
    print(f"contested: {len(contested)} (A semantic: {len(contested_type_a)}, "
          f"B boundary: {len(contested_type_b)})")
    print("deepseek distribution:", dict(ds_counts))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

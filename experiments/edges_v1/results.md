# edges_v1 Results — JEV edge classification vs gold-v1

Run: 2026-11-05 · 120 pairs × 3 runs = 360 JEV calls (`jev-latest`), 0 parse failures, p50 latency 947 ms

## Gates (pre-registered, run 1 only)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| P2-H1 | accuracy ≥ 0.80 | **115/117 = 0.9829**, CI95 [0.940, 0.995] | **PASS** |
| P2-H2 | contradicts recall = 5/5 | **5/5** | **PASS** |
| P2-H3 | contradicts precision = 5/5 | **5/5** (zero false conflicts) | **PASS** |
| P2-H4 | unrelated recall ≥ 0.90 | **103/104 = 0.990** | **PASS** |

## Per-class detail (run 1)

| Class | Recall | Precision |
|---|---|---|
| contradicts | 5/5 = 1.0 | 5/5 = 1.0 |
| supports | 7/8 = 0.875, CI95 [0.47, 0.98] | 7/8 = 0.875, CI95 [0.47, 0.98] |
| unrelated | 103/104 = 0.990 | 103/104 = 0.990 |
| supersedes | — (no gold) | **0 predictions on gold** (no over-prediction; API v1 remain-vs-removed correctly went to contradicts) |

Stability: 1/117 pairs flip label across the 3 runs (flip rate 0.009).

## Calibration — the headline finding

| Bucket | Accuracy | Errors |
|---|---|---|
| p ≥ 0.90 | **103/103** | 0 |
| 0.80–0.89 | 8/8 | 0 |
| < 0.80 | 4/6 | **both misses live here** |

Both errors sit at exactly p = 0.5 — JEV's probability output identifies its own uncertainty. Under the frozen decision rule (`p ≥ 0.80` proposes the edge, `0.50–0.79` routes to review), the deployed system makes 111/111 correct decisions on this gold set and routes the 6 uncertain pairs (5%) to human review. **Zero silent errors at the cost of a 5% review load** — the same margin/review structure that e2e_002 validated for record admission, now demonstrated for edge classification.

## The two misses (both on one boundary)

| pair | gold | JEV | content |
|---|---|---|---|
| pair_774a28306b1f | supports (annotator confidence 0.55, the weakest gold in the set) | unrelated @ p=0.5, unstable across runs | console feature-freeze vs no-new-panels |
| pair_fb70cdbdcc99 | unrelated | supports @ p=0.5 | migrations-before-start vs health-checks-no-DB |

Neither is random noise: both are the **sibling-constraint seam** of the ontology — two consistent constraints under one resource (console / database) where the supports/unrelated line depends on whether "refinement" must be stated in the text. The same seam produced all 3 dual-model contested pairs. The gold label itself was the lowest-confidence call in the annotation; JEV's p=0.5 + run instability independently flags the same pair as boundary.

## Contested pairs (excluded from metrics)

| pair | JEV run 1 | across 3 runs | channels said |
|---|---|---|---|
| pair_71dceef73b6c | unrelated @ 0.6 | stable | DeepSeek: supports, zcode: unrelated |
| pair_8d1921ca83ce | supports @ 0.88 | stable | DeepSeek: supports, zcode: unrelated |
| pair_e250c87793a9 | supports @ 0.98 | stable | DeepSeek: supports, zcode: unrelated |

JEV independently reproduces the DeepSeek reading on the benchmark↔margin boundary twice, and the zcode reading once — evidence the boundary is a property of the ontology, not of any single annotator.

## Limitations

1. Gold is dual-model annotated (κ = 0.886) with an 11/11 constructed-pair probe; no human gold. Shared-model-bias risk is bounded by the probe, not eliminated.
2. supports n = 8: the 7/8 CIs span [0.47, 0.98] — directional evidence only.
3. supersedes: unmeasurable (zero gold instances). Its absence as a prediction is good but weak evidence.
4. The edge question's criteria share an author with the schema; prompt-sensitivity sweep is future work.
5. Single question set, single model (jev-latest).

## Verdict

All four pre-registered gates pass. The `edge` question is validated for adoption into the product contract (`questions.v2.json` → contract bump), with two carry-forward items: (a) resolve the sibling-constraint seam by amending the schema definition or accepting the review-routing behavior, (b) measure supersedes on a purpose-built pair set before promoting that criterion.

## Threshold sensitivity — offline sweep (zero model calls)

Re-analysis of the frozen run data (`threshold_sweep.py` → `results/threshold-sweep.json`),
run-1 probability maps only.

### Edge proposal threshold (117 gold pairs)

| T | proposed | precision | review load | missed edges |
|---:|---:|---:|---:|---:|
| 0.50 | 13 | 0.923 | 0.0% | 1 |
| 0.55–0.90 | 12 | **1.000** | 0.9% | 1 |

The plateau is the finding: **every threshold from 0.55 to 0.90 produces identical
decisions** — 12 proposals, all correct, 0.9% review load. The only change is at T = 0.50,
where the two known p = 0.5 errors enter the proposed set (precision drops to 0.923). Policy
v2.3's frozen 0.80 sits in the middle of the plateau: it is not a fitted number, it is
insensitive to threshold choice across a 0.35-wide range. The single constant miss
(pair_774a, gold supports at unrelated p = 0.5) is a review-band resident at every threshold.

### Cascade recovery threshold (supersedes_003, 43 pairs)

| T | supersedes recall | repaired real conflicts | review band |
|---:|---:|---:|---:|
| 0.50–0.60 | **14/14** | **0** | 0 |
| 0.70 | 13/14 | 0 | 1 |
| 0.80–0.90 (frozen) | 12/14 | 0 | 2 |

The safety margin is structural, not tuned: the closest true replacement answers p_yes =
**0.63** and the closest real conflict answers p_yes = **0.10** — a 0.53-wide gap with
nothing in between. The frozen T_yes = 0.80 recovers 12/14; the data says 0.55 would recover
14/14 at zero repair cost. It stays at 0.80 for now: the band pairs are visible (review band,
replacement question attached), n = 2 behind the improvement is too thin to re-freeze policy
on, and lowering a safety threshold is a decision for a pre-registered protocol with more
data — exactly the discipline that produced these numbers in the first place.

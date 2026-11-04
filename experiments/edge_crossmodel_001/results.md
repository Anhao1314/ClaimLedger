# edge_crossmodel_001 Results — a pass that catches itself

Run: 2026-11-05 · 117 gold pairs × 3 runs = 351 deepseek-flash calls (t=0), 0 parse failures

## The numbers (run 1)

| Axis | deepseek-flash | JEV (edges_v1, frozen) |
|---|---|---|
| Accuracy | **117/117 = 1.0**, CI95 [0.968, 1.0] | 115/117 = 0.983 |
| contradicts recall / precision | **5/5 / 5/5** | 5/5 / 5/5 |
| Flip rate (3 runs) | 1/117 = 0.0085 | 1/117 = 0.0085 |
| Parse failures | 0/351 | 0/360 |
| Brier (contradicts) | **0.0004** | — |
| p50 latency | 1,834 ms | **947 ms** |

By the letter of the frozen gates: X1 PASS, X2 PASS (zero false contradicts), X3 composite PASS.

**The composite claim is void, and this document is where it gets caught.**

## The circularity

gold-v1 is dual-model annotated — and `deepseek-flash` was its **second annotation channel**
(`edges_gold/blind_annotate_deepseek.py`, a different prompt: the full 5-type spec vs this
experiment's 4-criteria rendering, but the same model, same pair texts, same temperature 0).
The 117 gold pairs are exactly the pairs where flash's own earlier labels agreed with the
other channel. So this experiment largely measures **flash agreeing with itself**, not
flash classifying edges correctly. It even "fixed" both of JEV's misses (pair_774a,
pair_fb70) — which is what self-consistency predicts, not evidence of superiority.

Contamination spreads unevenly:

| Axis | Contaminated? | Why |
|---|---|---|
| Accuracy | **Yes — void** | flash graded against a gold it co-authored |
| Flip rate | **Asymmetric** | flash is re-answering its own labels at t=0; JEV answered foreign gold |
| Parse failures | **No** | a property of model+task format, independent of gold |
| Latency | **No** | infrastructure |
| Brier (contradicts) | **No** | scored against gold labels, but confidence calibration on co-authored labels is still self-referential in part — treat as directional |

The frozen protocol's threat list missed gold co-authorship — that omission is recorded
here rather than edited into the frozen file. The protocol file stays as written; this
document is the correction.

## What survives

1. **Parse reliability transfers across question planes**: 0/351 on the 4-criteria
   probability-map format, consistent with judge_bench_001's 86% on a 3-label format two
   generations of prompting ago. (Directional — same model, different prompt.)
2. **Zero false contradicts** — the feared failure mode (a swapped judge inventing
   conflicts) did not appear. Contaminated in principle, but the failure's absence is the
   safe direction: contamination could inflate accuracy, it could not plausibly suppress
   false conflicts that would otherwise exist.
3. **Latency**: flash is ~2× slower (1,834 vs 947 ms p50) — a real cost of a swap that
   no contamination affects.

## What this experiment actually settles

**"The edge plane is judge-agnostic" is NOT established.** The composite is void until the
accuracy leg is run on pairs the test judge never labeled. The two clean paths, both already
planned:

1. **External blind eval** (human-annotated 40-pair subsample) — a human gold flash has
   never seen; the swap test reruns on it.
2. **Constructed hold-out pairs** labeled by construction (the supersedes_003 pattern —
   direction 21/21 was measured on pairs flash never annotated).

Until then the README claim stays: judge choice is **load-bearing on the relation plane**
(judge_bench_001) and **unproven either way on the edge plane** — with one more line in the
ledger: an experiment that reported its own circularity instead of shipping a clean-looking
PASS.

# edge_crossmodel_001 Protocol — is the edge plane judge-dependent?

Frozen: 2026-11-05 (before the first call; no edits after the first call).

## Question

judge_bench_001 answered "is the judge a commodity?" for the **relation** question:
accuracy was a tie, Jev won stability (0 vs 7 flips) and schema reliability (99.3% vs 86%).
The graph plane adds three more questions since; this experiment asks the same question of
the primary one — the frozen `edge` question on gold-v1 — before anyone can claim the edge
plane is judge-agnostic.

## Setup

- Pairs: the 117 in-gold pairs from edges_v1 (`pairs.jsonl`, `in_gold: true`). Contested
  pairs excluded — same scored set as JEV's 115/117.
- JEV reference numbers (frozen, edges_v1): accuracy 115/117 = 0.9829 (run 1);
  flip rate 1/117 = 0.0085 across 3 runs; parse failures 0/360; p50 latency 947 ms.
- Judge under test: `deepseek-flash`, temperature 0 (the deployment configuration used by
  e2e_002 for generation), 3 runs × 117 pairs = 351 calls.
- Prompt: faithful rendering of the frozen `edge` wire payload — criteria lines verbatim
  from contracts/questions.v3.json, state format identical to edges_v1
  (`Record A (src): … / Record B (dst): …`), JSON probability map over the four labels,
  normalized. The rendering is transport-shaped, not byte-identical to TypeSafe's — that
  difference is inherent to swapping providers and is disclosed.
- Parse failure = not valid JSON, missing labels, negative values, or non-normalizable
  probabilities. A parse failure counts as neither correct nor incorrect; rates are
  reported per run.

## Metrics (pre-registered, run 1 primary, runs 2-3 for stability)

- accuracy over parsed pairs, Wilson CI
- per-class recall/precision (supports, contradicts, unrelated; supersedes reported)
- flip rate across the 3 runs
- parse-failure rate
- Brier on the contradicts class (the safety-critical one)
- p50 latency

## Hypotheses (pre-registered)

| # | Hypothesis | Gate |
|---|---|---|
| X1 | flash accuracy ≥ 0.90 on the 117 pairs — below this, a judge swap fails outright regardless of the other axes | pass/fail |
| X2 | zero false contradicts (gold ≠ contradicts predicted contradicts) — the v7→v8 regression class must not appear under a swapped judge | pass/fail |
| X3 | **composite commodity test** (the judge_bench_001 rule, applied to the edge plane): flash accuracy ≥ JEV accuracy AND flash flip rate ≤ JEV flip rate AND flash parse-failure rate ≤ JEV parse-failure rate → "swap the judge, keep the pipeline" is defensible for the edge plane | pass/fail |

X1/X2 pass but X3 fails → the honest README claim is "the edge plane is judge-sensitive on
stability/schema axes", which is a *positive* result for the architecture (the judge choice
is load-bearing, not interchangeable).

## Threats to validity (pre-registered)

1. The DeepSeek prompt is a re-rendering of the frozen question; part of any gap is
   transport, not model. judge_bench_001 showed the same methodology gap for the relation
   question and the composite survived it; the comparison is like-for-like across the two
   experiments.
2. n = 117 with a 104-pair unrelated majority: accuracy alone is weak evidence; X2 and the
   per-class table carry the discriminating weight.
3. Three runs at t = 0 measure deployment-condition stability, not sampling diversity —
   deliberately narrower than judge_bench_001's t = 1.0 protocol, disclosed here.

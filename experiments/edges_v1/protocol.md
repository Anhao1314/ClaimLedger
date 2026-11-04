# edges_v1 Protocol — JEV edge classification vs gold-v1

Frozen: 2026-11-05 (before the first JEV call; no edits after the first call)

## Question under test

`edge` from `questions.v2.json`: a single choice question per pair returning a
probability map over `{supports, contradicts, supersedes, unrelated}`. Criteria
are verbatim from `contracts/edge-schema.v1.json`. This experiment validates the
question before any promotion into the product contract (the
`jev_relation_001` → `questions.v1.json` pattern).

## Inputs

- `pairs.jsonl`: 117 gold pairs (from `gold-v1.jsonl`, dual-model frozen) plus
  the 3 contested pairs flagged `in_gold: false`.
- Gold label = the label agreed by both annotator channels. The 3 contested
  pairs are run but excluded from every hypothesis metric; their behavior is
  reported separately.
- Runs: **3 independent runs per pair** (JEV state identical across runs).
  Primary metrics use **run 1 only** (frozen choice, no cherry-picking);
  runs 2-3 feed the stability report only.

## Metrics (pre-registered)

Primary (run 1, argmax label vs gold):

- accuracy = correct / 117, Wilson 95% CI
- per-class recall and precision with Wilson 95% CI
- 4×3 confusion matrix (predicted × gold)
- calibration buckets: accuracy at p(argmax) ≥ 0.90, 0.80-0.89, < 0.80

Stability (all 3 runs): per-pair label flip rate; pairs whose argmax ever
changes across runs.

## Hypotheses (pre-registered)

| # | Hypothesis | Gate |
|---|---|---|
| P2-H1 | argmax accuracy ≥ 0.80 | pass/fail |
| P2-H2 | contradicts recall = 5/5 (strict: a supersedes prediction on a gold-contradicts pair counts as a miss, disclosed separately) | pass/fail |
| P2-H3 | contradicts precision = 5/5 (zero false contradicts — the v7→v8 regression class) | pass/fail |
| P2-H4 | unrelated recall ≥ 0.90 | pass/fail |
| P2-H5 | directional only, no gate: supports precision/recall (n=8, CI reported), supersedes behavior, calibration monotonicity, contested-pair behavior | report |

**Class-imbalance caveat (pre-registered):** 104/117 gold pairs are
`unrelated`; a trivial all-unrelated classifier scores 0.889 accuracy. H1 is
therefore necessary but not sufficient — H2, H3, H4 carry the discriminating
evidence, and per-class rates are reported regardless of H1's outcome.

## Costs

120 pairs × 3 runs = 360 JEV calls, one question per call (cost_rule of the
question set: one request per decision). DeepSeek is not involved.

## Threats to validity (pre-registered)

1. **No human gold** — gold-v1 is dual-model with an 11/11 constructed-pair
   probe; shared-model-bias risk is disclosed in agreement-report.md.
2. **Zero gold `supersedes`** — supersedes precision is unmeasurable; its
   appearance as a prediction is reported directionally.
3. **Ontology boundary** — the supports/unrelated boundary was the sole
   disagreement axis between the two annotator channels (3 contested pairs);
   JEV predictions on those pairs may disagree with either channel without
   implying error.
4. **Designer overlap** — the question criteria were written by the same author
   as the gold schema; a prompt-sensitivity sweep (paraphrased criteria) is
   future work, not part of this freeze.

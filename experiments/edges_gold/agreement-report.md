# Phase 1 Agreement Report — edges_gold v1 (dual-model cross-validation)

Frozen: 2026-11-05 · Annotators: zcode (GLM, reduced guide) + DeepSeek (`deepseek-flash`, full spec inlined in blind prompt)

## Agreement

| Metric | Value |
|---|---:|
| Cohen's κ (unweighted, 5 classes) | **0.886** |
| Raw agreement | 0.975 |
| Expected agreement (chance) | 0.781 |
| Contested pairs | 3 / 120 |

Cohen's κ = 0.886 exceeds the 0.8 freeze threshold. The 0.781 expected-agreement value confirms the unrelated-class dominance required κ correction: the raw 0.975 would have been misleading on its own.

## Correctness probe (constructed ground truth)

11 pairs carry labels guaranteed by corpus construction, independent of any annotator:

| Probe | Result |
|---|---|
| zcode on 11 constructed pairs | **11/11** |
| DeepSeek on 11 constructed pairs | **11/11** |

This is the partial answer to "who grades the grader": both channels reproduce every label whose truth is fixed by design (5 designed conflicts + 6 paraphrase-family supports). It bounds — but does not eliminate — the shared-model-bias risk.

## Distribution comparison

| edge_type | zcode | DeepSeek |
|---|---:|---:|
| unrelated | 107 | 104 |
| supports | 8 | 11 |
| contradicts | 5 | 5 |
| supersedes | 0 | 0 |
| abstain | 0 | 0 |

Both channels found zero `supersedes` (no sampled pair carries an explicit temporal/version marker) and used zero `abstain`. Phase 2 implication: supersedes precision is unmeasurable on this gold set; report directional results only, per the sampling-table mitigation.

## Contested pool (excluded from gold)

All 3 disagreements are Type-A (semantic: relation vs no-relation). Zero Type-B (ontology-boundary) disagreements.

| pair_id | zcode | DeepSeek | Content |
|---|---|---|---|
| pair_71dceef73b6c | unrelated (0.70) | supports (0.78) | console no-new-backend-concepts vs no-new-panels |
| pair_8d1921ca83ce | unrelated (0.85) | supports (0.75) | benchmarks pre-registered vs README margin wording (CN) |
| pair_e250c87793a9 | unrelated (0.85) | supports (0.80) | benchmarks pre-registered vs README margin wording (EN) |

The disagreement pattern is coherent: DeepSeek reads sibling constraints under one principle as refinement (`supports` — "B is a specific application of A's no-post-hoc-tuning"); zcode requires the refinement to be stated in the texts. This is a genuine supports/unrelated ontology boundary, not annotator error — it is recorded as an ontology-ambiguity finding and feeds the Phase 2 prompt design.

**Gold rule applied:** contested pairs are excluded from the frozen gold (117 pairs) and listed here. No human tie-break was used; neither annotator's view was promoted.

## Gold set

`gold-v1.jsonl` — 117 pairs: unrelated 104, supports 8, contradicts 5. Each row carries both annotators' guide provenance and the min confidence of the two channels. Status is `proposed` per edge-schema.v1.json; the freeze commit is the confirmation event.

## Disclosed limitations

1. **No human gold.** Both annotators are models. κ validates schema executability and cross-model consistency, not correctness. The 11-pair constructed probe bounds the risk but does not remove it.
2. **Shared-bias risk.** Both channels may share training-data priors (e.g., reluctance to assert conflict, or affinity for principle-instance readings). The perfect probe score and the coherent disagreement pattern are evidence against gross shared bias, not proof of its absence.
3. **Upgrade path.** The pipeline is annotator-agnostic: a human blind annotation of any subset can replace or extend this gold and recompute agreement with the same scripts (`analyze_agreement.py`).

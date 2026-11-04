# zcode Annotation Report — edges_gold v1

Annotator: zcode (secondary, reduced guide: `docs/annotation-guide-reduced.md`)
Completed: 2026-11-05
Rows: 120/120

## Distribution

| edge_type | count |
|---|---:|
| unrelated | 107 |
| supports | 8 |
| contradicts | 5 |
| supersedes | 0 |
| abstain | 0 |

## Integrity checks (self-reported, before merge)

- All 5 high-confidence `contradicts` calls land on the 5 designed conflict record pairs from the e2e_002 corpus (panels, feature flags, structured logs, PostgreSQL scope, API v1).
- All 6 sampled cross-pairs of the 4 delta=0.2 margin wording variants are labeled `supports` — the cross-language paraphrase family is captured consistently.
- 3 pairs carry confidence < 0.7 (genuine judgment calls; kept determinate rather than abstain since a type was chosen with stated reasoning).
- 0 `supersedes`: no sampled pair contains an explicit temporal/version marker. Implication for Phase 2: supersedes precision is unmeasurable on this gold set; per the sampling-table mitigation, report directional results only.

## Bias note

107/120 `unrelated` is consistent with the declared sampling bias (82% low-overlap pairs from a heterogeneous corpus). This inflates raw agreement for any two annotators on the unrelated class; κ will correct for it, and Type-B disagreements should be read per-type, not in aggregate.

## Independence

The primary annotator (user) must not view `annotation-zcode.jsonl` or this report until their own 120 annotations are complete.

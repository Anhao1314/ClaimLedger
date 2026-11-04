# supersedes_003 Protocol — split the decision, not the sentence

Frozen: 2026-11-05 (before the first JEV call; no edits after the first call)

## Rationale (from two failed wording attempts)

supersedes_001 (0.643) and supersedes_002 (0.786) showed that re-wording the
`supersedes` criterion moves individual pairs in both directions (sup_d3
regressed under v3 with unchanged texts) instead of moving the decision
boundary. The diagnosis: JEV's `contradicts` prior on surface-negation and
value-conflict forms beats any wording of a four-way criterion. The frozen
rule barred a third wording — and both runs produced the evidence for a
structural change instead:

**Split "conflict vs replacement" into its own frozen binary question.**

Cascade (stage 2.5 becomes two questions on disjoint pair subsets):

1. `edge` question — **unchanged, contract v2 criterion** (the cascade is the
   alternative to wording iteration; byte-identity asserted at run time).
2. If and only if the edge argmax is `contradicts`, ask the candidate
   `replacement` question (questions.json in this directory): a binary
   yes/no — "is one of these two records a newer replacement of the other
   (stated succession, or two versions where a version number or effective
   date makes one newer)?" — with its own request and cache key.

Final decision rule (frozen, per run):

    edge argmax != contradicts        → that label
    edge argmax == contradicts:
        replacement p_yes >= 0.80     → supersedes (cascade-recovered)
        0.50 <= p_yes < 0.80          → contradicts (review band; NOT
                                         counted as supersedes anywhere)
        p_yes < 0.50                  → contradicts (conflict stands)

The disambiguation question is deliberately narrower than the four-way
criterion: it only ever sees pairs that already look conflicting, and it
answers one question — succession or genuine conflict.

## Pair set

`pairs.jsonl` is byte-identical to supersedes_002's (43 pairs; corrected
sup_d2/sup_f1; 12 seeded fresh unrelated controls; 14 supersedes / 9
distractors / 20 controls). The 24 verbatim gold-v1 members serve as the
regression core.

The disambiguation subset is computed, not hand-picked: every pair whose edge
argmax is `contradicts` in **any** of the 3 runs (the union, so borderline
pairs are measured too).

## Runs and metrics

- `edge` (contract v2) on all 43 pairs × 3 runs.
- `replacement` on the contradicted union × 3 runs.
- `direction` on all 14 supersedes-set pairs × 3 runs (it feeds the cascade's
  runtime shape: a recovered supersedes needs a direction).
Primary = run 1; final label computed per run for stability.

## Hypotheses (pre-registered, run 1)

| # | Hypothesis | Gate |
|---|---|---|
| S3-H1 | cascade supersedes recall ≥ 0.85 (14 pairs; the 10 v2-correct pairs are structurally safe, so the gate needs ≥ 2 of the 4 v2-missed pairs recovered at p_yes ≥ 0.80) | pass/fail |
| S3-H2 | **zero distractors with final label supersedes** — real conflicts must not be repaired into replacements (the new risk this design introduces; also reported: distractor p_yes rates below threshold, as latent-risk telemetry) | pass/fail |
| S3-H3 | zero controls with final label supersedes | pass/fail |
| S3-H4 | gold-member regression: 24 verbatim gold members — no final label other than the known pair_fb70cdbdcc99 boundary behavior | report |
| S3-H5 | direction accuracy on supersedes-decided pairs; stability of final labels; calibration of p_yes | report |

## Promotion rule (frozen)

All three gates pass → the `replacement` question is promoted into the product
contract (questions.v3: edge + replacement, version bump) and the cascade is
wired into judge.py stage 2.5 (contradicted pairs only). Any gate fails → the
cascade is rejected, v2 single-question remains, and the failure is reported;
no wording iteration on `replacement` without new evidence.

## Scope note (what this does NOT change)

The `relation` question still drives record actions (admit/review/conflict),
unchanged from e2e_002. A cascade-recovered supersedes does not un-flag a
relation-stage conflict; it only changes what the GRAPH proposes. Decoupling
record actions from a detected replacement is a separate, riskier change
touching e2e_002-validated behavior — future work, gated on its own protocol.

## Threats to validity (pre-registered)

1. The `replacement` criteria repeat v3's concepts (stated succession, version
   implication). If wording was the whole problem, this fails the same way —
   the bet is that the narrowed decision context, not the words, is what
   changes. The disambiguation subset is small (~13 expected), so per-pair
   churn is visible in full.
2. The 4 v2-missed pairs are known from prior runs (b1, c1, d1, d2). H1's
   gate is computed on the frozen pair file without reference to which pairs
   the cascade sees.
3. n=14 again; zero-error gates carry the weight.

# supersedes_003 Results — the cascade works; all gates pass

Run: 2026-11-05 · 43×3 edge (contract v2) + 14×3 replacement (union subset) + 14×3 direction = 213 JEV calls, 0 parse failures

## Gates (pre-registered, run 1)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| S3-H1 | cascade supersedes recall ≥ 0.85 | **12/14 = 0.857**, CI95 [0.60, 0.96] (v2 single-question: 0.643; v3 wording: 0.786) | **PASS** |
| S3-H2 | zero distractors repaired into replacements | **0/9** — dis_7's p_yes = **0.10**, all other distractors p_yes = 0.0 | **PASS** |
| S3-H3 | zero controls → supersedes | 0/20 | **PASS** |

**Frozen promotion rule: all gates pass → the `replacement` question is promoted and the cascade is wired into stage 2.5.**

## The decisive number: 0.10 vs 0.99

The design bet was that narrowing the decision — only conflicted-looking pairs, one binary question — beats re-wording a four-way criterion. The telemetry confirms it with unusual clarity:

- dis_7 ("removed in Q4", the hardest real-conflict look-alike): p_yes = **0.10** under the binary question, while the same pair sits at 0.99 contradicts — the cascade sees the succession question with fresh eyes and answers "genuine conflict" emphatically.
- sup_d2 (deprecated-as-of): p_yes = **0.99** → recovered. This pair failed under both v2 (supports @ 0.46) and v3 wordings.

The binary question separates what the four-way question could not: among *already-conflicting* pairs, "succession or genuine conflict" is a decision JEV makes cleanly, at both ends of the scale.

## The two remaining misses — both in the review band, both visible

| pair | edge | p_yes | outcome |
|---|---|---|---|
| sup_c1 (scope retirement) | contradicts | **0.76** | review band — 0.04 below the threshold |
| sup_d1 (PG 16 vs 15) | contradicts | **0.63** | review band |

Neither is silently misclassified: the frozen rule routes 0.50-0.79 to review, so both land in front of a human with the replacement question attached. The graph stays incomplete for these two; nothing is corrupted. Note sup_d1 — the pair that resisted two criterion wordings at 0.89 contradicts — answers the binary question at 0.63: the prior is weaker when the question is narrower, even where it does not clear the bar.

## Everything else held

- Direction question: **12/12 = 1.0** on supersedes-decided pairs.
- Gold members (24 verbatim): 23/24, sole miss = the known `pair_fb70cdbdcc99` boundary pair; **the cascade changed zero gold labels**.
- p_yes calibration is monotone and honest: ≥0.90 → 2/2 replacements; <0.50 → 9/9 genuine conflicts; 0.50-0.79 → correctly treated as "not confident enough to act".
- Stability: 1/43 (sup_d3, the known borderline; its final label flips between single-question supersedes and review-band).

## What was learned across the three experiments

| approach | supersedes recall | boundary violations |
|---|---|---|
| v2 wording (4-way) | 0.643 | 0 |
| v3 wording (4-way, revised) | 0.786 (churn, +1 regression) | 0 |
| **v2 + binary cascade** | **0.857** | **0** |

Same kernel, same pairs. The architecture lesson is the deliverable: **when one frozen question cannot hold two concepts apart, split the decision — don't re-word it.** This is the Jev-first doctrine (one decision, one frozen typed question) paying its way as an evaluation methodology, not just a runtime design.

## Carry-forward

1. Promote `replacement` into contracts/questions.v3.json (edge verbatim + new question), bump the active set, wire the cascade into judge.py stage 2.5 per the frozen decision rule.
2. Runtime note (unchanged scope): a cascade-recovered supersedes does not un-flag the relation-stage conflict — record actions stay as e2e_002 validated. The brief may annotate the disagreement in future work.
3. sup_c1/sup_d1 remain review-band: acceptable steady state, or a future direction question for the review band.

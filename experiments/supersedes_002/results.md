# supersedes_002 Results — better, still failing, and the reason not to iterate the wording again

Run: 2026-11-05 · 43 pairs × 3 runs (v3) + 14 × 3 (direction) + 2 × 3 (v2 baseline) = 177 JEV calls, 0 parse failures, 0 unstable pairs

## Gates (pre-registered, run 1, candidate v3 criterion)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| S2-H1 | supersedes recall ≥ 0.85 | **11/14 = 0.786**, CI95 [0.52, 0.92] (was 0.643) | **FAIL** |
| S2-H2 | zero supersedes-set → contradicts | **3 pairs** (was 4) | **FAIL** |
| S2-H3 | zero distractors → supersedes | 0/9 — **dis_7 @ 0.99 contradicts** (the at-risk boundary held under the looser criterion) | **PASS** |
| S2-H4 | zero controls → supersedes | 0/20 | **PASS** |

**Frozen promotion rule says: v3 is not promoted. The product criterion stays v2.**

## What the criterion revision actually did (paired, identical pairs)

Label flips between supersedes_001 (v2) and this run (v3) on carried pairs:

| pair | v2 | v3 | attribution |
|---|---|---|---|
| sup_b1 | contradicts @ 0.51 | **supersedes** | criterion (stated-replacement precedence) — texts unchanged |
| sup_d2 | supports @ 0.46 | **supersedes** | criterion — old text corrected, and the v2-baseline on the corrected text still says contradicts |
| sup_f1 | contradicts @ 0.61 | **supersedes** | shared: text correction AND criterion (v2 on corrected text already says supersedes) |
| sup_d3 | supersedes | **contradicts @ 0.84** | **regression** — texts unchanged, only the criterion changed |

Net +2. The gain is real but so is the regression: **criterion edits cause pair-level churn, not a systematic boundary shift.** The same kernel, same texts, one clause longer, and a previously-correct pair flips the wrong way with 0.84 confidence.

## The three remaining misses

| pair | label | probs | reading |
|---|---|---|---|
| sup_d1 (PG 16 vs 15) | contradicts @ **0.89** | supersedes 0.11 | the version clause is **invisible**: this pair is literally "two versions of the same requirement where a version number makes one newer" |
| sup_d3 (docs build source) | contradicts @ 0.84 | supersedes 0.16 | regression under v3 |
| sup_c1 (scope retirement) | contradicts @ 0.43 | supersedes 0.37 | "retired" is in the criterion's own verb list; near-flip but consistent across runs |

## What held perfectly

- Boundary: dis_7 ("removed in Q4", no succession statement) @ **0.99 contradicts** — the exact case the frozen rule feared did not happen.
- 24 verbatim gold-v1 members identified by text match: **23/24**, sole miss `pair_fb70cdbdcc99` — the known edges_v1 boundary pair (supports @ 0.5 there too). Consistent behavior, not a new regression.
- Direction question: **11/11 = 1.0** on v3-classified pairs, zero instability across runs.
- 0/43 unstable; distractor contradicts recall 9/9.

## The finding that matters

Two experiments, two criterion wordings, same pattern: JEV's `contradicts` prior on surface-negation and value-conflict forms is stronger than any wording of the supersedes criterion. The revision moved individual pairs in both directions instead of moving the decision boundary. **Prompt iteration on this criterion has hit diminishing returns; the frozen rule forbids a third wording without new evidence — and this run is that evidence: the limitation is in the single-question decision, not the sentence.**

Runtime safety is unchanged under either criterion: across 312 recorded edge calls (both experiments), zero wrong edges proposed. Misses land as either a conflict flag (records to review — visible, conservative, occasionally annoying: a PG 16 bump paralyzes two records) or a review-band judgment.

## Carry-forward

1. **The architecture-consistent fix is a second frozen question, not better wording**: when the edge argmax is `contradicts`, ask the targeted disambiguation — "is one of these two records a newer replacement of the other?" — and let the pair of answers decide (contradicts + replacement-yes + direction → supersedes edge proposal routed to review; contradicts + replacement-no → conflict as today). This matches the Jev-first doctrine: one decision, one frozen question; it also carries direction for free. Candidate protocol: supersedes_003, gated on the same 14-pair supersedes set + the 9 distractors (must not start "repairing" real conflicts into replacements).
2. Direction question promotion rides on the cascade's measurement (11/11 here, n still thin).
3. The v3 criterion file stays in this experiment as the frozen record of what was tried.

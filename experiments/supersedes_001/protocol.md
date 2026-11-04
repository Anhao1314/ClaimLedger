# supersedes_001 Protocol — the fourth criterion, measured

Frozen: 2026-11-05 (before the first JEV call; no edits after the first call)

## Why this experiment exists

gold-v1 contains zero `supersedes` instances, so edges_v1 could only show that
JEV never over-predicts supersedes (0 predictions on gold). It could not show
whether JEV *recognizes* a real replacement when one exists. The graph plane
has four edge types; three are measured, one is not. This experiment closes
that gap.

It also closes a second gap found during design: the frozen `edge` question
returns a relation type but **no direction**. `supersedes` is a directed edge
(src = the newer record, per edge-schema.v1.json), and runtime pair order is
arbitrary. A second, minimal question — asked only when supersedes is the
argmax — must carry the direction. That question is validated here before any
contract promotion (the jev_relation_001 pattern).

## Pair set (frozen in pairs.jsonl)

Three strata, 31 pairs. Labels are fixed **by construction or by gold-v1**;
no annotator is involved.

1. **Supersedes set (14 pairs, gold=supersedes).** Constructed pairs over
   corpus-familiar texts. The new record always carries an explicit
   replacement marker ("replaces", "revoked", "retired", "superseded",
   "no longer", "deprecated as of", version bumps) — the schema requires the
   replacement to be *stated*, and every pair states it. Five families:
   explicit value change (4), policy reversal (3), scope retirement (2),
   version/deprecation (3), cross-language reversal (1), threshold-mode
   reversal (1). Direction is balanced: 7 pairs have the new record as A,
   7 as B (`direction_truth` field). The constructed "new" records are
   experiment-only texts and must never be written to any record store.
2. **Distractor set (9 pairs, gold=contradicts).** Conflicts with **no**
   replacement marker — including the four designed corpus conflict pairs and
   the API v1 remain-vs-removed boundary case. These test that the explicit
   marker, not surface incompatibility, drives supersedes.
3. **Controls (8 pairs, gold from gold-v1).** 4 supports + 4 unrelated pairs
   taken verbatim from the frozen gold (provenance pair_ids included). One of
   the unrelated controls is pair_fb70cdbdcc99 — the known edges_v1
   boundary pair (JEV read it as supports @ p=0.5) — retained deliberately as
   a hard negative.

## Questions under test

- `edge` — byte-identical wire payload to contracts/questions.v2.json
  (asserted at run time against the experiment's own frozen copy).
- `direction` — new candidate question, asked only on the supersedes set:
  two-option choice ("A is the newer replacement" / "B is the newer
  replacement"), own request, state format identical to the edge question.

## Runs and metrics

3 runs per pair per question (31×3 edge + 14×3 direction = 135 calls).
Primary metrics = run 1; runs 2-3 feed stability only.

## Hypotheses (pre-registered)

| # | Hypothesis | Gate |
|---|---|---|
| S1-H1 | supersedes recall on the supersedes set ≥ 0.85 | pass/fail |
| S1-H2 | zero supersedes-set pairs classified as `contradicts` (a stated version update must never become a false conflict — the v7→v8 regression class) | pass/fail |
| S1-H3 | zero distractor pairs classified as `supersedes` (the explicit-marker boundary holds; distractors are gold contradicts) | pass/fail |
| S1-H4 | zero control pairs classified as `supersedes` | pass/fail |
| S1-H5 | direction accuracy on correctly-classified supersedes pairs — directional report with Wilson CI, no gate; it decides whether the direction question is promotable | report |

Secondary (reported, no gate): distractor contradicts recall, control-class
confusion, stability (label flips across runs), calibration buckets for the
supersedes set.

## Threats to validity (pre-registered)

1. **Constructed pairs are marker-explicit by design** — the supersedes set
   may be easier than organically-occurring replacements. The distractor set
   is the compensating control: the interesting claim is the *boundary*, not
   the recall number alone.
2. **No human gold** — labels are fixed by construction/gold-v1; this is
   stronger than dual-model gold but the pair texts were authored by the same
   person who wrote the question criteria.
3. **n=14** — recall CI will be wide (0.85 gate ≈ 12/14; CI ~[0.55, 0.97]).
   The zero-error gates H2-H4 carry more weight than the recall rate.

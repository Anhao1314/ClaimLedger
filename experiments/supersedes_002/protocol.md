# supersedes_002 Protocol — revised criterion, same gauntlet

Frozen: 2026-11-05 (before the first JEV call; no edits after the first call)

## What changed and why

supersedes_001 failed its recall gate (9/14 = 0.643) with two coherent failure
modes: version implication is invisible (PG 16 vs 15 → contradicts @ 0.85),
and surface negation outweighs a stated replacement (contradicts @ 0.51-0.61).
The negative side was flawless (0 supersedes over-predictions in 135 calls).

This experiment tests one change: the `supersedes` criterion text. Everything
else is held fixed. The candidate criterion (questions.v3.json, NOT yet in the
product contract):

> One record replaces the other and the replaced record is no longer intended
> to be followed. This includes a stated replacement (the newer record says it
> replaces, retires, revokes, deprecates, or that the older rule no longer
> applies) and two versions of the same requirement where a version number or
> effective date makes one newer. A stated replacement decides even when the
> records otherwise conflict

The two additions target the measured failure modes directly: version/effective
dating (mode 1) and stated-replacement precedence over value conflict (mode 2).
`contradicts`, `supports`, `unrelated` criteria, and every other question, are
carried verbatim from the contract — asserted at run time.

## Pair set (frozen in pairs.jsonl)

43 pairs, three strata. Same construction as supersedes_001 with two disclosed
corrections:

1. **sup_d2 corrected.** The old text dropped its "until the migration window"
   clause (which made old and new sequentially consistent — a construction
   flaw found in _001, disclosed there). Old is now the corpus-verbatim
   "API v1 must remain unchanged." This pair now forms a minimal pair with
   distractor dis_7: same old text, REMOVED (no replacement statement →
   gold contradicts) vs DEPRECATED-as-of (stated → gold supersedes).
2. **sup_f1 corrected.** Same flaw class: the authored new text carved out
   only "exploratory runs", leaving old and new coexistable. New text now
   retires the pre-registration rule outright.
3. **12 additional unrelated controls** sampled from gold-v1 with a disclosed
   seed (`random.Random(20261105)`) — the regression core for the criterion
   change: 9 distractors (the designed conflicts + boundary), 8 original
   controls (4 supports + 4 unrelated incl. the known-hard pair_fb70cdbdcc99),
   12 fresh unrelated. 21 of 43 pairs are verbatim gold-v1 members.

Baseline for comparison is supersedes_001 (same pairs except the two
disclosed corrections); the two corrected pairs are additionally re-run under
the v2 criterion (6 calls) so their paired delta is measured, not assumed.

## Questions under test

- `edge` (candidate v3) on all 43 pairs × 3 runs.
- `direction` (unchanged from supersedes_001) on the supersedes set × 3 runs.
- `edge` (contract v2) on the two corrected pairs only × 3 runs (baseline).

## Hypotheses (pre-registered, run 1)

| # | Hypothesis | Gate |
|---|---|---|
| S2-H1 | supersedes recall ≥ 0.85 (n=14) | pass/fail |
| S2-H2 | zero supersedes-set → contradicts | pass/fail |
| S2-H3 | zero distractors → supersedes (the boundary must survive the looser criterion — this is the gate most at risk from the revision) | pass/fail |
| S2-H4 | zero controls → supersedes (21 gold members incl. 12 fresh unrelated) | pass/fail |
| S2-H5 | direction accuracy — directional report, no gate | report |

## Promotion rule (frozen)

All four gates pass → the candidate criterion is promoted into
`contracts/questions.v3.json` (version bump; v2 retained frozen) and the
direction question becomes promotion-eligible on its S2 measurement.
Any gate fails → the criterion stays v2 and the failure is reported; no
third revision without new evidence.

## Threats to validity (pre-registered)

1. The criterion was revised by the same author who constructed the pairs and
   wrote the failing analysis — the corrections make two pairs cleaner, so
   part of any recall gain is text surgery, not criterion effect. The paired
   v2 baseline on the corrected pairs quantifies exactly that part.
2. dis_7 is the boundary at risk: "must be removed in Q4" states a demise but
   not a succession. If it flips to supersedes, S2-H3 fails and the criterion
   is too loose — that is the experiment working, not a nuisance.
3. n=14 again; zero-error gates carry more weight than the recall rate.

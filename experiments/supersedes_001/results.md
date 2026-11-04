# supersedes_001 Results — the fourth criterion has a recall problem

Run: 2026-11-05 · 31 pairs × 3 runs edge + 14 × 3 runs direction = 135 JEV calls, 0 parse failures

## Gates (pre-registered, run 1)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| S1-H1 | supersedes recall ≥ 0.85 | **9/14 = 0.643**, CI95 [0.39, 0.84] | **FAIL** |
| S1-H2 | zero supersedes-set → contradicts | **4 pairs became contradicts** | **FAIL** |
| S1-H3 | zero distractors → supersedes | 0/9 | **PASS** |
| S1-H4 | zero controls → supersedes | 0/8 | **PASS** |
| S1-H5 | direction accuracy (report) | **9/9 = 1.0** on classified pairs, CI95 [0.70, 1.0] | report |

Negative side is flawless: distractor contradicts recall 9/9 (including the API v1 boundary pair and all four designed corpus conflicts). JEV never says supersedes without an explicit marker — **precision-side behavior is perfect, recall is the weakness**.

## Failure anatomy — two modes, not noise

**Mode 1: version implication is invisible (sup_d1).**
"Use PostgreSQL 16 for all new deployments." vs "…15…" → **contradicts @ 0.85**, supersedes 0.15. This is *verbatim the annotation guide's supersedes example*. JEV reads a version bump as a value conflict with high confidence. Operational consequence in the wired runtime: the relation stage would flag this pair as a conflict and send both records to review — **a routine version bump would paralyze the affected records**.

**Mode 2: surface negation beats stated replacement (sup_b1, sup_c1, sup_f1).**
The new text both states the replacement ("revoked" / "retired" / "no longer required") and negates the old value ("no longer restricted to Tuesdays" vs "only on Tuesdays"). JEV weights the negation over the statement: contradicts @ 0.51 / 0.54 / 0.61 — all in the uncertain band, and sup_b1 is the one unstable pair (flips contradicts/supersedes across runs). Contrast with the passes: pairs whose marker is a *noun* ("replaces", "superseded", "retired", "废止") clear the bar; pairs whose marker is *negation phrasing* ("no longer") fail. The criterion text says "one record replaces the other" — JEV resolves it toward conflict when the surface form is negational.

**One construction flaw (sup_d2), disclosed against ourselves.**
The old text I authored says "API v1 must remain unchanged **until the migration window**" — which makes old and new *sequentially consistent* (unchanged until Q4, deprecated as of Q4). JEV's supports @ 0.46 is arguably correct; my gold is not clean. Excluding it, fair recall is 9/13 = 0.692 — the gate still fails, but the honest number is 0.69, not 0.64.

## What this means

1. **supersedes = high precision, low recall.** The explicit-marker boundary (S1-H3/H4) holds perfectly; the criterion never over-triggers. The cost of a miss is a *stale active record* — visible in review, never silent corruption.
2. **The runtime is safe by construction, but the graph stays incomplete.** Policy v2.3 routes every miss to review or relation-conflict; no wrong edge was ever proposed in 135 calls. What does not happen: automatic retirement of superseded records.
3. **The direction question works.** 9/9 with stable labels across runs — promotable after a larger direction set exists (n=9 is thin).
4. **This is a prompt/criterion problem, not an architecture problem.** The same kernel hits 115/117 on the 3-criterion gold. The supersedes criterion text lacks two things the failures need: version-update implication, and "a stated replacement outranks surface negation".

## Carry-forward (ordered)

1. **supersedes_002**: revise the `supersedes` criterion to explicitly cover version updates and stated-replacement precedence; pre-register the same 31 pairs + the corrected sup_d2; re-run. A criteria change is a question-set version bump — the v2 result stays as the historical record.
2. **Direction question promotion** rides on supersedes_002's direction measurement (larger classified set).
3. **Runtime guard worth keeping regardless**: a contradicts argmax on a pair whose texts contain an explicit replacement statement could route to *edge review* instead of record conflict — but only if supersedes_002 shows the revised criterion fixes recall; do not special-case prompts around a broken criterion.

## Limitations

- n=14 supersedes pairs, constructed by the same author as the criteria (disclosed in the protocol).
- One gold flaw found post-hoc (sup_d2), disclosed and excluded from the adjusted rate.
- Marker-explicit construction means organically-phrased replacements may be harder still, not easier.

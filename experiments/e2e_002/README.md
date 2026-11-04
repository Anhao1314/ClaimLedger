# e2e_002 — does the brief change the task outcome?

40 tasks × 4 arms × 3 runs. Protocol: [protocol.md](protocol.md). The pilot is
preserved under [../e2e_001/](../e2e_001/).

## Status (2026-11-05): v8 experiment COMPLETE

All 4 pre-registered hypotheses pass at n=40 tasks × 3 runs × 4 arms.
Results: [results.md](results.md). Frozen inputs unchanged from `e2e_002_v8`.

**v3–v8 design revision.** The first 480-call attempt was stopped before any scored
analysis. A pre-run health check found three design bugs: the 08/09 task queries
did not retrieve their own constraint, the 10_margin check rejected the correct
sentence because it contains "tuned", and D blocks sampled other tasks' conflict
pairs, so D could block instead of ignoring memory. Those are fixed; briefs and D
blocks are regenerated; runs are stratified to 320 calls (primary strata 3,
sanity strata 1) and frozen as `e2e_002_v8`; partial v2 results were discarded.

v8 fixes the conflict miss without the v5 false positives: stage 2 pairs only
when at least one side is admitted. The 15/16/21/22 conflicts surface, while
two low-relevance reviews no longer create a conflict. Tasks 01, 08, 09 and the
06 control query are calibrated to their own records; 09 was replaced (the
deployment record never admitted for the code task).

### Run halted (2026-11-04)

The 320-call run was stopped after 288 attempts. DeepSeek returned
`HTTP 402: Insufficient Balance` for 244 of them; only 26 passed before the
balance ran out. The task/arm matrix is incomplete, so the partial results were
deleted and are not analyzed. Top up the API key and rerun step 3 with
`--fresh`; the frozen artifacts are unchanged.

## 1. Generate the frozen artifacts (once)

```bash
python experiments/e2e_002/setup.py \
  --jev-env ~/.config/claimledger/jev.env
```

Writes the 55-record memory store, 40 tasks, hidden `check.py` files, explicit
and natural system prompts, frozen briefs, length-matched irrelevant blocks, and
`freeze.json`. It calls Jev to generate the briefs; the DeepSeek key is not
needed yet.

## 2. Validate offline

```bash
python experiments/e2e_002/selftest.py
```

Every starter must fail and every known good patch (or refusal) must pass.

## 3. Run

```bash
python experiments/e2e_002/run.py \
  --env-file ~/.config/claimledger/deepseek.env \
  --runs 3 --fresh --sleep 1
```

480 calls. If the provider is unstable, run one stratum at a time with
`--tasks` and use `--resume`; results append and `score.py` keeps the latest row
per task/arm/run.

## 4. Score

```bash
python experiments/e2e_002/score.py
```

Pass table, Wilson intervals, McNemar (C vs A/B/D), and token use.

## Arms

- **A** no memory
- **B** all confirmed records
- **C** the frozen `memory_brief`
- **D** length-matched irrelevant records — separates selection from brevity

## Rules

- Do not edit `memory/`, `tasks/`, or `prompts/` after `freeze.json` exists.
  `run.py` refuses to start if a hash changed.
- `--allow-unfrozen` is for debugging only; results from different freezes are
  not comparable.
- Conflict strata are reported separately: explicit (`BLOCKED` instruction) and
  natural (refusal rubric).
- Do not present a single headline pass rate; show intervals and strata.
# e2e_002 — does the brief change the task outcome?

40 tasks × 4 arms × 3 runs. Protocol: [protocol.md](protocol.md). The pilot is
preserved under [../e2e_001/](../e2e_001/).

## Status (2026-11-04)

**v3/v4 design revision.** The first 480-call attempt was stopped before any scored
analysis. A pre-run health check found three design bugs: the 08/09 task queries
did not retrieve their own constraint, the 10_margin check rejected the correct
sentence because it contains "tuned", and D blocks sampled other tasks' conflict
pairs, so D could block instead of ignoring memory. Those are fixed; briefs and D
blocks are regenerated; runs are stratified to 320 calls (primary strata 3,
sanity strata 1) and frozen as `e2e_002_v4`; partial v2 results were discarded.

Known and deliberately left in v3: 15/16/21/22 conflict briefs still miss a
conflict because stage 1 excludes one side before stage 2. That is reported as a
separate failure, not hidden by changing the judge mid-protocol.

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
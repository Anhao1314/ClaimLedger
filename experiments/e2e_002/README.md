# e2e_002 — does the brief change the task outcome?

40 tasks × 4 arms × 3 runs. Protocol: [protocol.md](protocol.md). The pilot is
preserved under [../e2e_001/](../e2e_001/).

## Status (2026-11-04)

40 tasks and a 55-record memory store are generated; all 40 hidden checks pass
the offline selftest. **Freeze and run are blocked:** TypeSafe/Jev returns
HTTP 451 ("Typesafe is not available in your region"), so the 34 new briefs
cannot be generated. No briefs, no freeze, no runs. The task set and harness are
ready; rerun step 1 from a network that can reach `api.typesafe.ai`.

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
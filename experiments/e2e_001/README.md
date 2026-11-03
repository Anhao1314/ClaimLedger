# e2e_001 — does the brief change the task outcome?

Pilot harness for the experiment described in [protocol.md](protocol.md).

## Status (2026-11-03)

Harness and task checks are validated offline (`python selftest.py`: 6/6 OK) and
the briefs are frozen. The pilot run itself is blocked: the DeepSeek API returns
`503 service_unavailable` ("service is too busy") for every configured model.
No results are committed. Rerun step 2 when the provider recovers.

## 1. Generate the frozen artifacts (once)

```bash
python experiments/e2e_001/setup.py \
  --jev-env ~/.config/claimledger/jev.env
```

This writes the memory store, six tasks, hidden `check.py` files, the frozen
brief for each task, the length-matched irrelevant blocks, and `freeze.json`.
It calls Jev to generate the briefs; the DeepSeek key is not needed yet.

## 2. Pilot run

```bash
python experiments/e2e_001/run.py \
  --env-file ~/.config/claimledger/deepseek.env \
  --runs 1 --fresh
```

Six tasks × four arms × one run = 24 calls. Every prompt and response is saved
under `results/<task>/<arm>/run1/`.

## 3. Score

```bash
python experiments/e2e_001/score.py
```

Prints a pass table, Wilson intervals, McNemar for C vs A/B/D, and token use.

## What the arms mean

- **A** no memory
- **B** all confirmed records
- **C** the frozen `memory_brief`
- **D** length-matched irrelevant records — the control that separates
  "selected the right records" from "supplied fewer tokens"

## Rules

- Do not edit anything under `memory/`, `tasks/`, or `prompts/` after
  `freeze.json` exists. `run.py` refuses to run if a hash changed.
- `--allow-unfrozen` exists only for debugging; results from different freezes
  are not comparable.
- The pilot is not evidence. With six tasks and one run it validates the
  harness. Expand to 40 tasks and three runs before making a claim.

## Cost

24 calls with `deepseek-flash` at temperature 0. `--max-calls` defaults to 100
and stops the run before overspending.
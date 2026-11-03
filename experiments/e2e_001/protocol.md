# e2e_001 — end-to-end memory experiment (pilot)

**Status:** pilot. Six tasks × four arms × one run. This validates the harness
and the task design; it is **not** powered to support a product claim.

## Question

Under the same model, system prompt, and task, does a ClaimLedger brief:

1. improve task success over no memory,
2. stay non-inferior to putting every confirmed record in the prompt, and
3. beat a length-matched block of irrelevant records — i.e. is the gain from
   selecting the right records, not merely from supplying fewer tokens?

## Arms

| Arm | Memory block |
| --- | --- |
| A | `(none)` |
| B | every confirmed record, verbatim, one per line |
| C | the `memory_brief` text for the task, frozen before any run |
| D | a length-matched block of records that excludes the task's relevant records |

D is the key control. Without it, C beating A only shows that short context
helps; it does not show that the selection is useful.

## Memory

`memory/records.jsonl` contains 50 confirmed records, all authored as
`operator`. They include:

- the six decisions the tasks depend on;
- two direct contradictions (`PostgreSQL` vs `PostgreSQL banned for analytics`;
  `no new console panels` vs `add a proposals panel`);
- 33 plausible but task-irrelevant decisions (frontend, auth, CI, billing, etc.).

Each task names its relevant records in `tasks/<id>/meta.json`. The brief is
generated once, frozen, and reused for every run. No judge call happens during a
run.

## Tasks

| id | type | target | relevant memory |
| --- | --- | --- | --- |
| 01_storage_postgres | constraint | `storage.py` | All storage must use PostgreSQL. |
| 02_retry_cap | constraint | `retry.py` | Retries must be capped at 3. |
| 03_analytics_storage | conflict | none (must output `BLOCKED`) | PostgreSQL / PostgreSQL banned for analytics |
| 04_console_panel | conflict | none (must output `BLOCKED`) | no new panels / add a proposals panel |
| 05_date_parser | irrelevant | `dateparse.py` | none (the Tuesday deployment rule must be ignored) |
| 06_control_math | control | `mathops.py` | none |

Each task has a hidden `check.py` that exits non-zero on failure. The harness
runs it after the model writes the target file. Conflict tasks are checked by
reading `response.txt`: it must start with `BLOCKED` and contain no code block.

## Prompt

All arms use the same system prompt and the same memory-block position:

```
SYSTEM: <prompts/system.md>
USER:
MEMORY:
<arm block>

TASK:
<task.md>
```

A has `(none)`. The model is asked to output only the full target file in one
python code block, or `BLOCKED` and no code when decisions conflict. No tools,
no repo browsing, no test execution.

## Runs

- Model: `deepseek-flash` (the configured default), temperature 0, `max_tokens`
  1200.
- One run per task × arm for the pilot; the full run uses three runs.
- Each run gets a fresh temp directory. Responses, prompts, and metadata are
  saved under `results/`.
- A call cap (`--max-calls`, default 100) prevents accidental spend.

## Metrics

- Primary: task pass rate (`check.py` exit 0).
- Secondary: conflict-task `BLOCKED` compliance; input/output tokens; latency;
  brief recall of the task's relevant records.
- Token counts are recorded per call. The pilot does not estimate cost.

## Freeze

`setup.py` writes `freeze.json` with sha256 for the memory store, tasks, system
prompt, briefs, irrelevant blocks, and this protocol. `run.py` refuses to run if
any hash differs. Re-running setup requires `--force` and produces a new
protocol version; results from different freezes are not comparable.

## Decision rule (full run, not the pilot)

- C > A on pass rate, with the lower bound of the paired 95% CI above 0.
- C non-inferior to B (C not worse by more than 5 percentage points).
- C > D on pass rate, showing the gain comes from relevant selection.
- C uses materially fewer memory tokens than B.

If C ≈ D, the value is brevity, not selection. If B > C, full context wins and
the brief's selection is losing information. If C ≈ A, the brief does not change
behaviour. Any of these is a publishable result; the wording in the README must
follow it.

## Prohibited after freeze

- adding or removing tasks, changing `check.py`, or editing task text;
- editing the memory store or the frozen briefs;
- changing the system prompt, model, temperature, or max tokens mid-run;
- dropping failed runs or parse failures from the denominator;
- reporting the best run instead of the mean.

## Limitations

Six single-file tasks, one model, one run, no tool use, no human review in the
loop. It tests whether the brief carries usable constraints, not whether an
autonomous coding agent improves at its job. The full run expands to 40 tasks
and three runs; even then the sample is small and the report must show CIs.

## Files

```
protocol.md
setup.py              generates memory, tasks, briefs, D blocks, freeze
run.py                runs tasks × arms × runs
score.py              aggregates results, Wilson CI, McNemar
memory/records.jsonl
tasks/<id>/           task.md, starter.py, check.py, meta.json
prompts/system.md
prompts/briefs/       frozen brief per task
prompts/irrelevant/   frozen D block per task
results/              prompts, responses, results.jsonl
freeze.json
```
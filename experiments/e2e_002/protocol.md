# e2e_002 — end-to-end memory experiment (40 tasks)

**Status:** pre-registered, not yet run. 40 tasks × 4 arms × 3 runs.

This is the powered version of the e2e_001 pilot. The pilot's inputs and results
are preserved under `experiments/e2e_001/`; this is a new freeze and a new
result set, not a continuation.

## Question

Under the same model, system prompt, and task, does a ClaimLedger brief:

1. improve task success over no memory;
2. stay non-inferior to putting every confirmed record in the prompt; and
3. beat a length-matched block of irrelevant records — i.e. is the gain from
   selecting the right records, not merely from supplying fewer tokens?

## Arms

| Arm | Memory block |
| --- | --- |
| A | `(none)` |
| B | every confirmed record, verbatim, one per line |
| C | the `memory_brief` text for the task, frozen before any run |
| D | a length-matched block of records that excludes the task's relevant records |

D is the key control. If C does not beat D, the product is brevity, not
selection.

## Memory

`memory/records.jsonl` contains 55 confirmed records, all authored as
`operator`. They include:

- the decisions the 10 constraint tasks depend on;
- five direct contradictions: PostgreSQL vs PostgreSQL banned for analytics;
  no new console panels vs add a proposals panel; structured logs vs no
  structured logs; API v1 unchanged vs removed in Q4; dependencies pinned vs
  floating; feature flags off vs on;
- plausible task-irrelevant decisions (frontend, auth, CI, billing, etc.).

Each task names its relevant records in `tasks/<id>/meta.json`. Briefs are
generated once, frozen, and reused for every run. No judge call happens during a
run.

## Tasks: 40, four strata

| stratum | count | shape |
| --- | ---: | --- |
| constraint | 10 | one project decision must be applied; task text does not state its value |
| conflict | 10 | 6 explicit, 4 natural |
| irrelevant | 10 | plausible memory that must be ignored |
| control | 10 | no memory needed; all arms should pass |

**Explicit conflict** tasks tell the model to output `BLOCKED` and no code when
decisions conflict. They measure whether the brief's conflict section is obeyed.

**Natural conflict** tasks do **not** mention `BLOCKED`; the system prompt only
says to explain when a human decision is needed. The check requires no code block
and a refusal/ask phrase (conflict, human, cannot proceed, needs review, etc.).
This is a rubric, not a human label; it is reported separately.

Every task has a hidden `check.py` that exits non-zero on failure. The harness
runs it after the model writes the target file. Conflict checks read
`response.txt`.

## Prompt

All arms use the same memory-block position:

```
SYSTEM: prompts/system.md (explicit) or prompts/system_natural.md (natural)
USER:
MEMORY:
<arm block>

TASK:
<task.md>
```

A has `(none)`. The model is asked to output only the full target file in one
python code block, or a refusal when decisions conflict. No tools, no repo
browsing, no test execution.

## Runs

- Model: `deepseek-flash`, temperature 0, `max_tokens` 8000.
- The model emits reasoning tokens before the answer; any run ending with
  `finish_reason=length` is retried once with a doubled budget (16000). If it
  still truncates, it is recorded as a failure, never silently dropped.
- Three runs per task × arm; 40 × 4 × 3 = 480 calls.
- Each run gets a fresh temp directory. Responses, prompts, and metadata are
  saved under `results/`; `--resume` skips runs that already passed.
- `--max-calls` caps spend; batches can be run per stratum.

## Metrics

Primary: task pass rate (`check.py` exit 0), paired by task.

Secondary:

- explicit conflict `BLOCKED` compliance; natural conflict refusal compliance;
- prompt tokens (C vs B), completion tokens, latency;
- brief recall of the task's relevant records;
- control-stratum pass rate as a harness-noise check.

Report Wilson 95% CIs, exact McNemar for paired differences, and the token
ratio. No p-value is reported without its interval.

## Decision rule (pre-registered)

Let pass rate be the mean over the three runs, majority per task.

- **H1:** C > A, exact McNemar p < 0.05.
- **H2:** C > D, exact McNemar p < 0.05.
- **H3:** C is non-inferior to B: the paired difference (B − C) is not worse
  than 5 percentage points.
- **H4:** C uses materially fewer prompt tokens than B (report the ratio; no
  threshold for "material").

If H1 holds but H2 does not, the value is shorter context, not selection. If B
beats C by more than 5pp, the brief is losing information. If C ≈ A, the brief
does not change behaviour. Any of these is a result; the README must follow it.

## Freeze

`setup.py` writes `freeze.json` (v2) with sha256 for the memory store, tasks,
system prompts, briefs, irrelevant blocks, and this protocol. `run.py` refuses
to run if any hash differs. Re-running setup requires `--force` and is a new
protocol version; results from different freezes are not comparable.

## Prohibited after freeze

- adding or removing tasks, changing `check.py`, or editing task text;
- editing the memory store or the frozen briefs;
- changing the system prompts, model, temperature, or token budget mid-run;
- dropping failed or truncated runs from the denominator;
- reporting the best run instead of the mean.

## Limitations

Single-file tasks, one model, no tools or multi-turn sessions. Natural-conflict
scoring is a keyword rubric. The memory is synthetic. Even with 480 calls this
is a modest experiment; the report must show intervals and strata, not a single
headline number.

## Files

```
protocol.md
setup.py              generates memory, tasks, briefs, D blocks, freeze
run.py                runs tasks × arms × runs
score.py              aggregates results, Wilson CI, McNemar
selftest.py           offline validation of every check.py
tasks_extra.py        the 34 added tasks and the natural-conflict prompt
memory/records.jsonl
tasks/<id>/           task.md, starter.py, check.py, meta.json
prompts/system.md, prompts/system_natural.md
prompts/briefs/       frozen brief per task
prompts/irrelevant/   frozen D block per task
results/              prompts, responses, results.jsonl
freeze.json
```
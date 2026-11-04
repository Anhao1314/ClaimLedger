# e2e_001 pilot results — 2026-11-04

**Status: pilot. Six tasks, one run per arm. This validates the harness and
shows a direction; it is not evidence of a general effect.**

- Model: `deepseek-flash`, temperature 0, `max_tokens` 8000
- Frozen artifacts: `freeze.json` (`e2e_001_pilot_v1`)
- Length policy: one retry at 16000 if `finish_reason=length`
- 24 scored runs (A/B/C/D × 6 tasks × 1 run)

## Pass rate

| task | A none | B all records | C brief | D irrelevant |
| --- | ---: | ---: | ---: | ---: |
| 01_storage_postgres | fail | PASS | PASS | fail |
| 02_retry_cap | fail | PASS | PASS | fail |
| 03_analytics_storage | fail | PASS | PASS | fail |
| 04_console_panel | fail | PASS | PASS | fail |
| 05_date_parser | PASS | PASS | PASS | PASS |
| 06_control_math | PASS | PASS | PASS | PASS |

| arm | pass | 95% Wilson CI |
| --- | ---: | --- |
| A none | 2/6 (33%) | 10%–70% |
| B all records | 6/6 (100%) | 61%–100% |
| C brief | 6/6 (100%) | 61%–100% |
| D irrelevant | 2/6 (33%) | 10%–70% |

C vs A: 4 discordant, 0 the other way, exact McNemar p=0.125.
C vs D: same. C vs B: identical. **With six tasks, none of this is significant.**

## Prompt cost

`prompt_tokens` from the API, per task:

| task | B all records | C brief | C as share of B |
| --- | ---: | ---: | ---: |
| 01_storage_postgres | 777 | 305 | 39% |
| 02_retry_cap | 777 | 258 | 33% |
| 03_analytics_storage | 724 | 321 | 44% |
| 04_console_panel | 723 | 331 | 46% |
| 05_date_parser | 728 | 221 | 30% |
| 06_control_math | 702 | 195 | 28% |

The brief delivers the same pass rate on this set at roughly **one third to one
half of the prompt tokens**. Completion tokens are lower too on most tasks,
because the model does not spend reasoning on distractor records.

## What the arms did

- **A (no memory)**: on 01 it kept the starter's SQLite backend; on 02 it used
  the requested `attempts`; on 03/04 it wrote code instead of blocking. It
  passed only the two tasks that need no memory.
- **B (all records)**: found the constraints and both contradictions. On 03/04
  it answered exactly `BLOCKED`.
- **C (brief)**: same decisions as B, including both `BLOCKED` answers, at a
  fraction of the prompt tokens.
- **D (irrelevant, length-matched)**: passed only the two memory-free tasks.
  On 03/04 it hit the token limit after the retry and produced no block; it
  never had the conflicting records, so it could not have resolved them.

The D result is the important control: C's advantage is not merely "less
context". A length-matched block of plausible but irrelevant decisions does not
produce the right behaviour.

## What this does not prove

- Six single-file tasks, one run, one model. CIs overlap heavily.
- It tests whether the brief carries constraints and contradictions into a
  single completion, not whether a tool-using coding agent improves over a long
  session.
- The conflict task uses a required `BLOCKED` marker; it measures compliance
  with an explicit instruction, not natural escalation behaviour.
- D's 03/04 runs are truncated even after the length retry. Its failures are
  still consistent with having no conflict information, but the truncation is a
  harness caveat, not a clean behavioural result.
- No cost estimate: token counts are recorded, pricing is provider-specific.

## Next

Expand to 40 tasks and three runs, keep the same freeze discipline and decision
rules. Do not present this pilot as "the brief improves task success"; it is a
harness validation with a consistent direction.

## Artifacts

- `results/results.jsonl` — one row per attempt (latest row per task/arm/run wins)
- `results/score.json` — table, Wilson intervals, McNemar, tokens
- `results/<task>/<arm>/run1/` — prompt, response, per-attempt outputs, metadata
# e2e_005 Protocol — the test-repair loop (ReAct-lite), memory vs no memory

Frozen: 2026-11-07, before the first call. No edits after the first call.

## Question

Every earlier experiment was a **one-shot pipeline**: generate once, test once.
The JD this project targets asks for an "Agent core engine" that runs the full
intelligent-test-development loop (generate → execute → observe → repair). This
experiment adds that loop and measures two things:

1. Does an executable-test feedback loop lift task success over one-shot?
2. Does governed memory still matter **inside** the loop — does a judged brief
   make the repair faster/better than no memory at all?

## Task set (inherited, frozen)

The 30 **executable** v8 tasks (meta.blocked == false, targeted files with
runnable checkers). The 10 BLOCKED-type tasks are excluded: their correct
answer is a refusal ("BLOCKED"), and feeding "expected BLOCKED" as repair
feedback would trivialize the loop.

## Arms

- **R0 — no memory + repair**: same prompts as e2e_002 arm A (`MEMORY: (none)`),
  plus the repair loop.
- **R1 — judged brief + repair**: same prompts as e2e_002 arm C (the frozen
  `prompts/briefs/<task>.txt`), plus the repair loop.

One run per task per arm. Model deepseek-flash, temperature 0.

## Loop rules (frozen)

Attempt 1: the standard one-shot prompt. Run the task's `check.py` against the
extracted code in a temp dir.

On failure, attempt 2 (and at most attempt 3) sends:

```
SYSTEM: <same>
USER: MEMORY:\n<block>\n\nTASK:\n<task.md>\n\nYOUR PREVIOUS ATTEMPT:\n<full previous response>\n\nTEST FEEDBACK (the test failed):\n<checker output, last 600 chars>\n\nFix the code so the tests pass. Output only the full corrected file in a python code block.
```

- Max 3 attempts. Pass short-circuits. Checker output is the standard stderr of
  the task's own check.py — no hand-written hints.
- Budget: 40 tasks × 2 arms, hard cap 240 generation calls.
- Resume-safe: one results row per (task, arm) with the full attempt log.

## Hypotheses and gates (pre-registered)

| # | Hypothesis | Gate |
|---|---|---|
| E5-H1 | The repair loop beats one-shot without memory | paired McNemar over the 30 tasks: R0 final > A run-1 baseline, p < 0.05 |
| E5-H2 | Repair does not hurt the memory arm | R1 final ≥ C run-1 baseline (paired, ≥ 0 net) |
| E5-H3 | Memory still adds value inside the loop | R1 final − R0 final ≥ 3 tasks (30-task set) |
| E5-H4 | Memory shortens the loop | directionally: mean iterations-to-pass R1 < R0 (report, no gate) |

## Baselines (inherited, frozen)

e2e_002 v8 run-1 results for the same 30 tasks, arms A and C, read from
`experiments/e2e_002/results/results.jsonl`; pairing is per task.

## Interpretation rules (frozen)

- H1 fails (loop doesn't beat one-shot) → the v8 tasks are either too easy or
  checker feedback is insufficient; reported as-is, no loop adoption.
- H3 fails (memory adds nothing inside the loop) → the memory value claim is
  narrowed again: it lives in governance/audit, not in repair speed. This is a
  legitimate negative result and must be reported as such.
- H2 fails (repair hurts the memory arm) → investigate prompt contamination
  (test feedback leaking expected answers) before any conclusion.

## Threats (pre-registered)

1. Checker feedback can leak expected values (e.g., an assertion diff showing
   "postgresql" vs "sqlite"). That is genuine TDD-style feedback, equal across
   arms, and is the point of the experiment — but it means H1/H2 measure
   "repair given tests", not "reasoning".
2. Attempt-1 pass rates should approximately reproduce e2e_002's per-task
   results (bit-identical prompts); drift is provider nondeterminism, reported.
3. n=30, single run: McNemar pairs only; no cross-run stability claim.
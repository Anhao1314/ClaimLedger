# e2e_005 Results — the repair loop works, and memory makes it better

Run: 2026-11-07 · 30 executable v8 tasks × 2 arms, ≤3 attempts each · deepseek-flash, temperature 0

## Gates (pre-registered)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| E5-H1 | Repair beats one-shot without memory | R0 **27/30** vs A 21/30 · McNemar b=6 c=0, **p=0.031** | **PASS** |
| E5-H2 | Repair not worse with memory | R1 **30/30** vs C 26/30 · b=4 c=0 (zero regressions) | **PASS** |
| E5-H3 | Memory adds value inside the loop | **Δ = +3 tasks** (30 − 27) | **PASS** |
| E5-H4 | Memory shortens the loop | mean iterations 1.10 vs 1.15; R0 repaired 4/7 initial fails, **R1 repaired 3/3** | report |

## The headline

**Memory + repair = 30/30 on the executable task set.** No memory + repair = 27/30. One-shot best (inherited C) = 26/30. The loop and the memory are additive: the repair loop rescues 4 of R0's 7 initial failures; governed memory rescues **all 3** of R1's and prevents 4 of the initial failures entirely (first-attempt: R1 27/30 vs R0 23/30).

Mechanism check: the checker stderr is the only feedback signal — no hand-written hints. This is genuine generate → execute → observe → repair, equal across arms (disclosed in the protocol: test feedback can leak expected values; that is the point of TDD-style repair, and it applies to both arms).

## Why this matters for the target JD

This is the experiment that makes the project speak the JD's language — **"基于 LLM 构建 Agent 核心引擎，实现全流程智能化测试开发"** and **"通过使用结果数据分析提升模型效果"**:

1. A real act-observe-repair loop over executable tests (not a prompt-chain demo): checker output → repair prompt → re-run → pass.
2. The result feeds back into the model's behavior measurably: 21 → 27 (loop) → 30 (loop + governed memory), zero regressions.
3. The memory arm is the project's thesis applied to QA: a judged, conflict-aware, staleness-annotated brief improves repair without changing the loop mechanics.

## Honest notes

- H2's McNemar p=0.125 (b=4, c=0) — directionally clean but not significant at n=30; the claim is "no regressions + perfect final score", not "significant lift over C".
- Single run, 30 tasks: no cross-run stability claim.
- R1's 30/30 is on the executable subset only; the 10 blocked tasks are excluded by design (refusal tasks trivialize under "expected BLOCKED" feedback).
- Token cost: repair attempts carry 8k-token budgets; the loop is not cheap — per-task cost roughly doubles for the 7 tasks that needed repair.

## Files

`results/results.jsonl` (60 rows, full attempt logs), `results/score.json`, prompts and per-attempt responses under `results/<task>/<arm>/`.
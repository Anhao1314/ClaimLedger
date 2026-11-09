# e2e_003 Results — RAG vs judged composition: parity, and the judge as bottleneck

Run: 2026-11-07 · 312 generation jobs + 63 retried slots (probe starter fix) · deepseek-flash, temperature 0 · 3 runs/arm/task

## Gates (pre-registered, run 1)

| # | Hypothesis | Result | Verdict |
|---|---|---|---|
| E3-H1 | E is a sane RAG baseline | **35/40 = 0.875** | **PASS** |
| E3-H2 | E is conflict-blind (≤6/10, < C's 9/10) | **8/10** | **FAIL** |
| E3-H3 | F non-inferior to C (≥0.825) | **34/40 = 0.85** | **PASS** (margin 2.5pp) |
| E3-H4 | F keeps conflict capture (≥8/10) | **9/10** | **PASS** |
| E3-H5 | probe F ≥5/8 AND C ≤3/8 | **F 6/8, C 6/8** (E 5/8) | **FAIL** |

## The headline: task-success parity

On this corpus (55 decision records, 40 tasks), the retrieval method barely moves task success:

| Arm | overall | conflict strata |
|---|---|---|
| C judged brief (inherited) | 35/40 | 9/10 |
| **E pure RAG** (embedding top-5, no judge) | **35/40** | 8/10 |
| F composition (union + judge) | 34/40 | 9/10 |

**The judge adds no task-success gain over good retrieval here.** Its measured value is elsewhere: write gate, conflict surfacing in the brief, supersession, calibration, audit — none of which this metric sees. The README claim must move accordingly (protocol's frozen interpretation rule for H2).

## Why H2 failed — the conflict tasks are blocked-tasks

8/10 conflicts caught by pure RAG because the conflict probes are **BLOCKED tasks**: when both conflicting records land in the top-5 block, the generator sees the contradiction itself and refuses. The judge's pairwise localization matters for *routing and audit* (who gets reviewed, what the brief says, what the human sees), not for this end-to-end outcome. E's 2 misses (03_analytics_storage 0/3, 19_storage_natural 0/3) are retrieval misses, not conflict-blindness.

**Framing revision (as frozen):** "pure RAG is conflict-blind" is not supported end-to-end on explicit conflict pairs. What *is* supported: (a) irrelevant retrieval is fatal (D 21/40 inherited), (b) stale/versioned conflicts — where contradictions are not co-located in one context — remain untested until e2e_004.

## H5's failure has two causes, one of them is the finding

**Cause 1 — probe design flaw (disclosed):** the Chinese probe tasks necessarily contain English identifiers (`storage.py`, `delta=0.2`, `config`, `API`), which bridge the lexical gap. C scored 6/8, not ≤3/8. Tasks that avoid shared identifiers are near-impossible to write for code tasks; the clean cross-lingual test needs prose-only tasks.

**Cause 2 — the judge is the bottleneck (the real finding):** probe_storage:

| arm | result | mechanism |
|---|---|---|
| E pure RAG | **3/3** | embedding rank 2 = the PG record → stuffed → model sets `BACKEND="postgresql"` |
| F composition | **0/3** | same candidate included, but the admit question judged it **not applicable** to the Chinese task → brief says "none admitted" → model keeps starter `sqlite` |
| C judged (lexical) | 0/3 | lexical missed the record entirely |

**The composition's weakest link is the judge, not the retriever.** On cross-lingual tasks the conservative admit stage discards exactly the records embedding retrieval was added to find. Pure RAG beats the composition on this probe. This is the honest counter-result the experiment existed to expose.

## What holds up

- E as a baseline: 0.875 — retrieval quality dominates (D's 0.525 vs E's 0.875).
- F non-inferior: 34/40 within the 5pp margin; F catches conflict 9/10, all of E's misses (03, 19) are fixed by the union.
- Token means: E 222, F 283, C 304 (C inflated by probes) — the brief is not cheaper than raw top-5.
- All probe failures for C/E/F concentrate on `probe_retry` (0/3 all arms: "retry" ≠ "retries" lexically; embedding also missed) and `probe_storage` (see above).

## Carry-forward (ordered)

1. **e2e_004 becomes the load-bearing experiment**: versioned-doc staleness is where task success *should* diverge (old chunk ≠ new chunk — not co-located, generator can't see the conflict). Empty corpus until built (K8s plan frozen at scenario level).
2. **Admit-stage cross-lingual conservatism** — a candidate fix is a task-language-aware admit prompt or admitting when p is thin but retrieval is strong; any change needs its own pre-registration (no third wording without evidence).
3. **Probe redesign** — prose-only tasks without shared identifiers for a valid cross-lingual test.
4. README: replace "judged brief wins task success" framing with "retrieval quality dominates task success; the judge's value is governance + audit, measured elsewhere".

## Threats to validity (updated)

- Starter fix post-first-call (probe boilerplate only, task texts/checkers unchanged — manifest note).
- Task 07's "no code block" failure is inherited (C failed 3/3 in e2e_002; E/F一致), not new.
- n=40 + 8; CIs wide; H3's margin (2.5pp) is inside noise but was pre-registered as non-inferiority, not superiority.
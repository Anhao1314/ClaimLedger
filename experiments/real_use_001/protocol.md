# real_use_001 Protocol — 14 days of real use, no synthetic tasks

Frozen: 2026-11-05 (day 0). No edits after day 1 begins.

## What this is

The system is complete and measured on synthetic corpora (relation, edges, supersedes).
What it does not have yet is the evidence that matters for a governance layer: **does it
survive real daily use** — real tasks, real agents, real human confirmations, real friction?
This protocol runs the store as production memory for 14 consecutive days and measures what
the audit trails already record. No new code changes to jev_first during the window; no
experiment runs against the store; the system is frozen at contract v3 (commit 4d787b3).

## Store and surfaces

- Store: `~/.jev-work/` (records, proposals, edges, judgments, outcomes, agents — all
  hash-chained, all outside the repo).
- Agents: zcode (agent sessions) and doubao-work (MCP) are the registered identities.
- Human surface: console (`python -m jev_first console --store ~/.jev-work/records.jsonl
  --dir ~/.jev-work`) or CLI (`confirm`, `reject`, `edges`, `edge-confirm`, `edge-reject`,
  `outcome`).

## Usage rules (the whole commitment)

1. **Consult**: at least one real `memory_brief`/`memory_decide` call per active day — an
   agent checks memory before doing real work. No minimum task count; the call must precede
   work the memory could actually affect.
2. **Propose**: when an agent learns something durable during real work, it proposes a
   record (never writes). Expectation over 14 days: ≥ 3 real proposals. No daily quota.
3. **Decide**: pending record proposals and edge proposals are confirmed/rejected by the
   human as they appear — the daily cost is 2-3 minutes. Rubber-stamping is worse than
   leaving things pending; a rejection is as valuable as a confirmation.
4. **Score**: when an admitted constraint meets reality (a task where it applied and the
   outcome is visible), record an outcome (`upheld` / `overturned` / `unclear`) against the
   judgment. Target: **≥ 10 scored outcomes** over the window.
5. **Journal**: one optional line per day in `~/.jev-work/friction.md` — anything that
   blocked real work, felt awkward, or surprised. Honest friction is a deliverable, not a
   failure.

## What gets measured on day 14 (all from the audit trails, nothing self-reported)

| Metric | Source | Pre-registered threshold |
| --- | --- | --- |
| Active days (≥ 1 decide/brief call) | judgments.jsonl | **≥ 12 / 14** |
| decide + brief calls | judgments.jsonl | report |
| Proposals created / confirmed / rejected | proposals.jsonl | ≥ 3 created; confirm+reject ≥ 2 |
| Edge proposals created / confirmed / rejected | edges.jsonl | report (graph is young; no floor) |
| Scored outcomes (upheld/overturned) | outcomes.jsonl | **≥ 10**; upheld rate reported with Wilson CI; **Brier** |
| Gate integrity | any direct record writes bypassing proposals | **zero violations** |
| Friction entries | friction.md | report, verbatim themes |

**Failure handling, frozen now:** if < 10 scored outcomes exist at day 14, the calibration
claim is reported as "insufficient outcomes" and the protocol does NOT extend silently — a
decision to extend is a new, explicit decision.

## Pre-registered interpretations

- Upheld rate ≥ 0.70 with ≥ 10 outcomes → the judge's admissions hold up in real use
  (calibration sanity for the portfolio claim).
- Confirm rate ≥ 0.50 on record proposals → agents propose at the right threshold; a much
  lower rate means agents over-propose (policy tightening signal).
- Zero gate violations is a hard pass/fail: any agent-written record breaks the story the
  whole project tells.
- Friction is scored qualitatively only; it never retroactively changes thresholds.

## Day-0 baseline (captured 2026-11-05, before day 1)

12 records (zcode 8, doubao-work 4) · 1 proposal confirmed · 0 edges · 4 sealed judgments ·
1 outcome · 2 registered agent identities. Snapshot: `results/day0.json`.

## Non-goals

No new experiments on this store, no schema changes, no prompt changes, no console redesign.
Anything the window reveals becomes a *candidate* change, decided after day 14.

---

## STATUS: SUSPENDED (2026-11-06, Day 1)

Suspended by owner decision before Day 1 usage began — skipped in favor of the
next build phase. Gates G1–G4 are **withdrawn, not claimed**: no result exists and
none will be reported for this protocol. What the partial window did produce
(2026-11-05, Day 0 + same-day A2A work) and remains valid as operational evidence:

- 9 sealed judgments, 13 records, 2 confirmed proposals (1 from `doubao-work` via
  the live cross-vendor A2A), 1 outcome, all chains verified.
- A live cross-vendor A2A (Doubao Work reading zcode-authored records; a
  doubao-work proposal held pending until human confirmation) — verified from the
  audit trails, not self-reports.
- Real-use observations logged in `~/.jev-work/friction.md` (lexical cross-language
  gap, dedupe-vs-conflict tension, wording fate) — these feed the post-window fix
  batch, which this suspension unblocks.

Any future re-run of a real-use protocol gets a fresh freeze; this file's gates
are dead. The 14-day discipline itself is preserved in the record: the window
held its "log, don't fix" rule for every observation it produced.

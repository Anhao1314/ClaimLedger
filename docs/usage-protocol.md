# 14-day real-use protocol

**Purpose:** find out whether the loop is usable outside a demo. The output is a
usage log and a one-page exit report — not a testimonial.

## Roles

| Role | Who | Does |
| --- | --- | --- |
| Operator | one human | confirms proposals, records outcomes, keeps the daily log |
| Agent host | Claude / Cursor / ZCode / Doubao Work | calls `memory_brief` before work, `memory_propose` after a decision |
| Ledger | this repo | selects, judges, seals, waits for the operator |

Use one store directory per engagement, e.g. `~/.jev-<project>`. Never put API
keys or client names in the repository.

## Setup (day 0, ≤30 minutes)

1. Create the store and register identities:

   ```bash
   python -m jev_first record --store ~/.jev-acme/records.jsonl \
     --text "All storage must use PostgreSQL." --source operator
   python -m jev_first agent-register --dir ~/.jev-acme \
     --name operator --kind human
   python -m jev_first agent-register --dir ~/.jev-acme \
     --name claude --kind agent
   ```

2. Connect the MCP server (`--dir ~/.jev-acme`) to the agent host, and paste the
   block from [agent-instructions.md](agent-instructions.md).

3. Seed 10–20 decisions that already exist in the project. If the project has
   none written down, the first week will mostly be record-building; note that
   in the report.

4. Start the console:

   ```bash
   python -m jev_first console --store ~/.jev-acme/records.jsonl --dir ~/.jev-acme
   ```

## Daily loop (≤5 minutes)

- **Before a task:** the agent calls `memory_brief`. The operator records whether
  the brief changed the plan: `yes` / `no` / `blocked`, plus one line why.
- **After a settled decision:** the agent calls `memory_propose`. The operator
  confirms or rejects it the same day in the Proposals panel.
- **After a wrong verdict:** the operator records `upheld` / `overturned` /
  `unclear` against an admitted record.
- **At end of day:** append one row to the log.

```csv
date,task,brief_used,changed_plan,why,proposals,confirmed,rejected,outcomes
2026-11-04,add retries to billing client,yes,yes,brief capped retries at 3,2,1,1,0
```

## Pre-registered success criteria

Measured over 10 working days:

- ≥30 briefs, ≥15 proposals, ≥10 confirmed, ≥5 outcomes.
- Median time from proposal to decision < 24 hours.
- At least 3 cases where the brief changed a decision (`changed_plan=yes`).
- At least 1 case where the brief surfaced a contradiction before it shipped.

Stop and write a negative report if any of these hold:

- <5 briefs per week (the agent is not using it).
- >50% of proposals rejected as noise (the write path is too chatty).
- Zero outcomes after 14 days (the calibration loop is not closing).

## Privacy and publication

Publish aggregate counts, plus at most 5 briefs/proposals with identifiers and
domain details redacted and the operator's written consent. Never publish API
keys, client names, repository contents, or unredacted record text.

## What to watch (known failure modes)

- paraphrased proposals that the lexical duplicate check misses;
- a highly relevant record demoted to `thin margin`;
- Chinese task text with English records (recency fallback, not lexical match);
- proposals accumulating because the console was not opened.

Each occurrence gets one line in the exit report. These are the inputs to the
next product decision, not embarrassments to hide.

## Exit report (one page)

1. Setup time, daily time, number of working days.
2. Counts: briefs, proposals, confirmed, rejected, outcomes.
3. Three cases where the brief changed or prevented something.
4. Three failures, with the exact record/proposal ids.
5. Would the operator keep using it? Yes / no / only if X changes.
6. What the operator did instead on days the tool was not used.
# Agent instructions

Copy the block below into your `CLAUDE.md`, `.cursorrules`, `AGENTS.md`, or the
equivalent host file. Without it the agent has the MCP tools but no reason to
call them — a tool that is never invoked is indistinguishable from no tool.

Two things must be true before this block does anything:

1. The MCP server is registered (see [MCP server](../README.md#mcp-server)).
2. `TYPESAFE_API_KEY` is set in the environment the server runs in. Without it
   every decision is degraded to `review` and the loop still runs, but nothing
   is admitted.

---

## The block

```markdown
## Project memory (ClaimLedger MCP)

This project uses a Jev-first memory layer exposed as MCP tools prefixed
`memory_`.

BEFORE starting any non-trivial task:
1. Call `memory_decide` with the task description.
2. Read the brief it returns:
   - ACTIVE CONSTRAINTS — follow them.
   - NEEDS HUMAN REVIEW — do not act on these; ask me before relying on them.
   - UNRESOLVED CONFLICTS — stop and ask; never pick a side yourself.
3. If the result says `degraded`, the judge was unreachable. Treat every record
   as review and ask me before acting.

AFTER a significant decision is settled (tech choice, architecture, constraint,
reversal), call `memory_propose` with the decision as ONE standalone sentence that
makes sense without this conversation. It returns `status: pending` plus a
`proposal_id`; the decision is **not active memory** until I confirm it in the
console or CLI. Tell me the proposal_id and wait for confirmation.

Never:
- record secrets, credentials, or transient chatter
- record a guess as if it were a decision
- treat a pending proposal as an active constraint
- silently resolve a conflict the brief reports
```

---

## Why each line exists

| Line | Failure it prevents |
| --- | --- |
| Call `memory_decide` before work | The agent never looks at memory and the layer is invisible |
| Follow ACTIVE, ask on REVIEW | `review` means a human has not confirmed it — the agent must not self-promote |
| Stop on UNRESOLVED CONFLICTS | The model's default is to pick a side; the layer exists to stop that |
| Handle `degraded` | An outage must not look like a confident exclusion |
| Record standalone sentences | Transcript excerpts make retrieval and conflict detection unreliable |
| Never record secrets | The record store is a plain JSONL file on disk |

---

## Verifying it works

After the next task, check that the loop actually ran:

```bash
python -m jev_first audit --log ~/.jev-memory/judgments.jsonl
```

A non-zero judgment count means the agent called `memory_decide`. Zero means the
instructions were not picked up — check that the MCP server is registered and
that the host file is in the right scope (project vs user).

To confirm records are landing:

```bash
python -m jev_first verify --store ~/.jev-memory/records.jsonl
```

---

## Two-week protocol

The point of installing this is not to have it installed. It is to produce the
data the project is missing:

| Day | Action |
| --- | --- |
| 1 | Register the MCP server, paste the block, run one task end to end |
| 2–13 | Work normally. Let the agent record and decide. |
| daily | Open `python -m jev_first console`, click one outcome |
| 14 | Run `python -m jev_first calibrate` and read the first real calibration table |

At day 14 you will have one of two answers, and both are useful:

- **Calibration data exists** → the project gains the half it was missing.
- **No outcomes collected** → the honest conclusion is that even you did not
  need it, which is the most valuable result this project could produce next.

---

## Known gaps the agent will hit

| Gap | What you will see | Where it is tracked |
| --- | --- | --- |
| Lexical candidate selection | A relevant record is not in the brief because the task shares no words with it | [JEV-FIRST.md](JEV-FIRST.md), contract v2 topic field |
| Candidate cap of 6 | A large store needs pre-filtering | `jev_first/select.py` |
| Judge latency 1–5 s | First `decide` on a new task is slow; repeats hit the cache | [jev.md](jev.md) measured latency |
| Calibration scores `admit` only | Outcomes on `review` entries do not move the Brier score | `jev_first/calibration.py` |
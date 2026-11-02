# ClaimLedger · a Jev-first memory layer for agents

> **Status (2026-11) — an engineering artifact, not a research contribution.**
> This repository's founding question — do agents act on superseded conclusions, and does
> status filtering prevent it — was answered before this repository existed, with stronger
> evidence: *Revoked but Still Authoritative* ([arXiv:2609.08258](https://arxiv.org/abs/2609.08258),
> Sep 2026) tested 5 memory systems × 9 models × 9 policy scenarios and found that **no system
> enforces revocation by default**. The governed-memory design space is covered by
> [GPM](https://arxiv.org/abs/2608.12476), [MemTX](https://arxiv.org/abs/2607.23929) and
> [PLACE](https://arxiv.org/abs/2610.25179).
>
> What remains here is a small, dependency-free implementation with one unusual property:
> **the model does not own judgment — a frozen question set, a deterministic policy, and a
> sealed decision log do.** The generation model can be swapped without touching any of them.
> [Why the research framing was withdrawn](docs/DECISION.md) ·
> [the literature check](docs/prior-art.md) · [why Jev sits at the center](docs/JEV-FIRST.md)

**What it does:** an agent writes decisions into an append-only, hash-chained record store.
For each task, a candidate selector picks ≤6 records; a judgment engine asks the
[TypeSafe Jev](https://docs.typesafe.ai/introduction) System One model a frozen set of typed
questions (one `admit` choice per record, pairwise `relation` for conflict localization,
`governing`); a deterministic policy turns probabilities into actions; a sealed log makes every
decision auditable and every probability calibratable against human outcomes.

```
records (hash chain, no stored status)
   → select (scope + lexical recall + recency fallback, cap 6 — deliberately coarse)
   → judge  (stage 1: admit per record, judged alone · stage 2: pairwise conflict
             localization · stage 3: governing)
   → policy (margin rule · contradiction ⇒ review, never auto-exclude)
   → sealed judgment log (hash chain) → brief / audit / calibration views
```

## Quick start

```bash
python -m pip install .
python -m jev_first record --store records.jsonl --text "All storage must use PostgreSQL." --source agent
python -m jev_first decide --store records.jsonl --task "Write a storage adapter for analytics"
python -m jev_first brief  --store records.jsonl --task "Write a storage adapter for analytics"
python -m jev_first verify --store records.jsonl
```

Zero third-party dependencies, Python 3.9+. Records carry no status field: validity is a
judgment, not a datum. The brief separates what the agent may rely on (`admit`) from what
needs a human (`review` — conflicted, thin margin, or hedged).

## MCP server

```bash
export TYPESAFE_API_KEY=…   # without it the server answers in degraded mode
python -m jev_first.mcp_server --dir ~/.jev-memory
```

Six tools: `memory_record`, `memory_decide`, `memory_brief`, `memory_outcome`,
`memory_calibrate`, `memory_audit`. Tool failures come back as `isError` results; the server
never crashes on a tool. Without a key, decide/brief answer degraded — every record review.

## Results

| Experiment | Result | Artifact |
| --- | --- | --- |
| Relation judgment (30 frozen pairs) | contradiction recall 10/10, false suppression 0/20 — **PASS** | [jev_relation_001](experiments/jev_relation_001/README.md) |
| Cross-model replay (Jev vs DeepSeek) | **29/29 label agreement** on comparable pairs | [crossmodel](experiments/jev_relation_001/crossmodel-deepseek-flash.json) |
| Borderline stability (5×5) | ambiguous pairs flip, unambiguous never → **margin rule** | [borderline-stability](experiments/jev_relation_001/borderline-stability.json) |
| Constraint delivery (premise_001 v1.1) | memory-layer delivery **non-inferior** to prompt delivery | [premise_001](experiments/premise_001/results.json) |

Known limitation, recorded honestly: the candidate selector is lexical, so a record with zero
token overlap is not selected. Semantic recall is deferred to a topic field (contract v2).

## What was withdrawn and why

The original framing — a novel "decision ledger" — was withdrawn after a two-hour literature
check found the space occupied ([review](docs/prior-art.md)); the demo, landing site, wiki, RAG
adapter and brand assets built around it were removed in the cleanup. What was kept is the
part the checks could not kill: an auditable judgment layer with an honest boundary.

| Doc | Content |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | current architecture + policy state machine |
| [docs/JEV-FIRST.md](docs/JEV-FIRST.md) | why the model owns judgment; the cut list |
| [docs/DECISION.md](docs/DECISION.md) | the withdrawn claim, recorded |
| [docs/prior-art.md](docs/prior-art.md) | the literature check |
| [docs/jev.md](docs/jev.md) | the Jev adapter: contract, measured latency, privacy boundary |
| [docs/design-v2.zh-CN.md](docs/design-v2.zh-CN.md) | legacy design record (pre-inversion) |

## Boundaries

- This is a local memory/judgment component — **not an autonomous agent and not a truth detector**.
- The Jev adapter is the only network path; it requires explicit consent and sends the judged
  text to a third party. Records never leave the machine otherwise.
- Calibration v1 scores `admit` entries only; `review`/`exclude` outcomes are recorded but not
  yet scored.
- The candidate selector is lexical; a record with zero token overlap is not selected.
- No web UI, no daemon, no cross-machine sync.

[MIT](LICENSE)
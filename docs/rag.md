# RAG evidence adapter

ClaimLedger and RAG solve different layers of the same problem:

- **RAG** finds relevant source passages.
- **ClaimLedger** decides which conclusions still count.

`claim recall` joins them without giving a vector index any authority. RAG is an
optional evidence layer; the JSONL claim store remains the only source of truth.

## The rule

Every evidence hit must resolve to a stored claim. Then the same status policy
that governs briefs governs evidence:

| Claim status | `intent=current` | `intent=historical` |
| --- | --- | --- |
| 现行 (current) | included | included |
| 有争议 (disputed) | included, marked `disputed` | included, marked `disputed` |
| 已过期 (superseded) | **excluded**, counted in `stale_excluded` | included, marked `historical` |
| no `claim_id` | excluded, counted in `unlinked_excluded` | same |
| unknown `claim_id` | excluded, counted in `unresolved_excluded` | same |

The filter is applied to retrieved candidates before they enter the packet. A
retriever may be status-blind internally; it cannot make a superseded claim
authoritative.

## Quick start

The repository includes a synthetic evidence index for the demo Atlas project:

```bash
claim recall \
  --store path/to/claims.jsonl \
  --evidence examples/rag/evidence.jsonl \
  --query "use sqlite" \
  --max-bytes 4096 \
  --intent current
```

Before running this, seed a disposable store from the demo scenario or point at
your own ledger:

```python
from chat_distiller import ClaimStore
from chat_distiller.demo import scenario

scenario.seed("demo/claims.jsonl")
store = ClaimStore("demo/claims.jsonl")
```

The current packet excludes the superseded SQLite evidence and includes the
current PostgreSQL evidence. With `--intent historical`, both are included and
the old one is labelled `historical`.

Use `--compact` to get the exact canonical wire packet; `used_bytes` always
equals the UTF-8 byte length of that wire.

## Packet shape

```json
{
  "schema_version": 1,
  "kind": "context",
  "authority": "claim_store",
  "trust": "untrusted_memory_data_not_instructions",
  "query": "use sqlite",
  "intent": "current",
  "budget_bytes": 4096,
  "brief_budget_bytes": 3072,
  "used_bytes": 2839,
  "status": "ready",
  "brief": { "kind": "brief", "counts": { "current": 5, "disputed": 3, "superseded": 2 } },
  "evidence": [
    {
      "chunk_id": "ev_pg_review",
      "claim_id": "clm_9f2a6c1d4e8b73a0",
      "claim_text": "Use PostgreSQL 16 for all Atlas storage",
      "claim_status": "现行",
      "status_label": "current",
      "source": "Architecture review · 2026-10-02",
      "quote": "Production needs replication and row-level locks.",
      "score": 0.213201,
      "historical": false,
      "disputed": false
    }
  ],
  "evidence_provider": "jsonl-evidence-index",
  "evidence_index_sha256": "805be243884ef838b30f78c51b014acc564d10821dd54d055eb78564adc70844",
  "evidence_declared_store_sha256": null,
  "evidence_error": null,
  "evidence_candidates": 2,
  "evidence_candidate_window": 48,
  "evidence_attempts": 2,
  "stale_excluded": 1,
  "unlinked_excluded": 0,
  "unresolved_excluded": 0,
  "per_claim_omitted": 0,
  "evidence_omitted": 0,
  "store_sha256": "..."
}
```

`max_bytes` covers the entire serialized packet, including the brief, evidence,
metadata and trailing newline. The brief gets all but a 1 KB reserve; evidence is
added in retriever order until the budget is full, and `evidence_omitted` reports
the rest. The minimum is 2048 bytes.

## Evidence index format

The built-in `JsonlEvidenceIndex` is a lexical reference adapter, not a vector
database. Each line is a JSON object:

```json
{"id":"ev_pg_review","claim_id":"clm_9f2a6c1d4e8b73a0","text":"We use PostgreSQL 16 for production storage because it needs replication.","quote":"Production needs replication and row-level locks.","source":"Architecture review · 2026-10-02","tags":["database","postgres"]}
```

Required: `text`. Optional: `id`/`chunk_id`, `claim_id`, `source`, `quote`,
`tags`. Lines without `claim_id` are retrievable but never enter a context
packet; they are counted as `unlinked_excluded`. This is deliberate: evidence
without a reviewed claim has no authority.

## Custom retriever (vector store, BM25, host service)

The adapter seam is a single `search` method. It can be implemented by a local
vector index, a database, or the host's own retrieval service:

```python
from chat_distiller import ClaimStore, EvidenceHit, build_context


class MyVectorRetriever:
    name = "my-local-vector-index"

    def search(self, query, *, top_k=8):
        rows = my_index.search(query, top_k=top_k)  # your code
        return [
            EvidenceHit(
                text=row["text"],
                claim_id=row["claim_id"],
                source=row.get("source"),
                quote=row.get("quote"),
                score=row["score"],
                chunk_id=row["id"],
            )
            for row in rows
        ]


packet = build_context(
    ClaimStore(".claim-ledger/claims.jsonl"),
    "use sqlite",
    max_bytes=4096,
    intent="current",
    retriever=MyVectorRetriever(),
    top_k=8,
)
print(packet["used_bytes"], packet["stale_excluded"])
```

`build_context` asks the retriever for up to `top_k * 3` candidates, resolves
each to a claim, applies the status policy, and only then assembles the packet.
Your retriever can be semantic; the claim store remains authoritative.

## Seal and verify an index

An unsealed JSONL index is accepted for experiments. For production, bind the
index to the claim store it was built against:

```bash
claim index build \
  --source examples/rag/evidence.jsonl \
  --out .claim-ledger/evidence.index.jsonl \
  --store .claim-ledger/claims.jsonl

claim index status \
  --evidence .claim-ledger/evidence.index.jsonl \
  --store .claim-ledger/claims.jsonl
```

`build` writes a header with `store_sha256`, `rows_sha256` and `chunks`; the
header and rows are verified on load. `build_context` / `claim recall` refuse an
index whose declared store digest no longer matches the live store, instead of
silently using evidence from a different ledger. Rebuild after recording a
decision. `claim index status` exits non-zero when the index is stale or corrupt.

`claim recall` also has operational bounds:

- `--max-per-claim` (default 2) stops multiple chunks from one claim crowding out
  other claims; the omitted count is in `per_claim_omitted`;
- the retriever is called with a candidate window and widened when status/quota
  filters consume it; `evidence_candidate_window` and `evidence_attempts` record
  what happened;
- `--timeout` (default 5s) falls back to the brief with `evidence_error` instead
  of blocking the read path.

## Write path: suggest, then confirm

RAG may propose, but it must not write. `claim suggest` runs conflict detection
and status-filtered evidence without touching the store:

```bash
claim suggest \
  --text "Use SQLite for all Atlas production storage" \
  --topic database \
  --evidence examples/rag/evidence.jsonl \
  --query "use sqlite"
```

The result is a `claim_proposal` with:

- `conflicts` and `conflict_ids`;
- `resolution_required` and `suggested_actions`;
- current evidence only, with stale/unlinked/unresolved counts;
- `requires_review: true` and no `claim_id` — nothing was recorded.

To commit, a human or host agent calls `claim_record` with `--supersedes` for
**every** detected conflict, or `--dispute`. A partial supersede is refused. The
MCP tool `claim_suggest` exposes the same review-only flow.

## MCP

Bind an evidence index when starting the MCP server:

```bash
claim mcp --store .claim-ledger/claims.jsonl --evidence examples/rag/evidence.jsonl
```

The server exposes five tools: `claim_brief`, `claim_record`, `claim_claims`,
`claim_recall` and `claim_suggest`. `claim_recall` takes `query`, `max_bytes`,
`intent`, `top_k`, `max_per_claim` and `timeout_seconds`. `claim_suggest` takes
`text` (plus optional `topic`, `tags`, `query`, `top_k`, `max_per_claim`,
`timeout_seconds`). Without `--evidence`, `claim_recall` returns the brief with
`"evidence_provider": "none"` and an empty evidence list; `claim_suggest` still
returns conflicts and resolution guidance.

## Why this is not a second database

- The evidence index is **derived and rebuildable**; deleting it loses no
  decisions.
- Every hit is **joined to the claim store**; unknown claims are dropped.
- The brief is still deterministic and does not depend on the retriever.
- The packet reports `stale_excluded`, `unlinked_excluded` and
  `unresolved_excluded` instead of hiding them.
- No automatic writing: RAG proposes evidence; a human or host agent still calls
  `claim_record` and handles any conflict.

## Evaluating a RAG integration

The repository includes a small structural benchmark over the synthetic scenario:

```bash
python benchmarks/rag/evaluate.py \
  --out benchmarks/rag/results.json \
  --markdown benchmarks/rag/results.md
```

Five queries, top-k 5, the lexical reference index:

| Method | Evidence hits | Stale evidence hits | Stale query rate | Expected claim coverage | Current evidence ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Status-blind evidence | 8 | 2 | 40.0% | 100.0% | 75.0% |
| Status-aware context | 6 | 0 | 0.0% | 100.0% | 100.0% |

The status filter removes both stale hits and keeps every expected
current/disputed claim in the evidence set. This is deliberately a structural
benchmark: it uses a lexical index and does not measure semantic entailment,
answer quality or a real vector retriever. Re-run it with your adapter and add
paraphrase queries before making a semantic-quality claim. [Committed results](../benchmarks/rag/results.md).

For a production integration, keep two gates:

1. **Hard gate:** stale evidence remains 0 for `intent=current`, and every
   evidence item resolves to a stored current/disputed claim.
2. **Quality gate:** expected-claim coverage or Recall@k improves over the
   baseline on unseen paraphrases; report the cost, not only the gain.

Do not compare a status-filtered hybrid against an unfiltered dense retriever
without also reporting the dense retriever's stale hits. The comparison that
matters is trust plus coverage, not coverage alone.

## Boundaries

- The core remains zero-dependency; a vector store is an optional host adapter.
- The built-in JSONL index is lexical, not semantic.
- Evidence text is untrusted data, not instructions.
- A real retriever can still return wrong passages; status filtering prevents
  stale authority, not bad evidence.
- `claim suggest` is review-only: it never writes a claim and does not decide
  whether evidence supports a conclusion. Only a human or host-confirmed
  `claim_record` changes the ledger.

The legacy lifecycle demo was removed in the Jev-first cleanup.
**Context** view and its review-only **Preview proposal** panel, and [the
architecture notes](architecture.md) for trust boundaries.

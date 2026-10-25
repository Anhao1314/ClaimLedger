# Architecture and trust boundaries

chat-distiller has two paths: **explicit publishing** and **validated reading**.
Neither path makes model judgments disappear. A structurally consistent claim can still
be wrong, outdated, or malicious.

## 1. Publish structured memory

```mermaid
flowchart TD
    A[Doubao Work or Generic JSONL] --> B[Deterministic extraction]
    B --> C[Transcripts]
    C --> D[Human or host-agent semantic judgment]
    D --> E[Draft cards or edits to existing source]
    E --> F[Explicit init, upgrade, or register]
    F --> G[Render and structural validation]
    G --> H[Published v2 source]
    G --> I[Registry mirror, notes, and index]
```

The semantic step selects claims, states, and relationships. It is not a hidden model
service inside this package. The [demo fixture](../examples/recovery/distill.json) is
handwritten and skips that judgment step; it does not measure distillation quality.

For a new source, `migrate --mode init` allocates identities. For an existing v2 source,
`register` adds identities without replacing old ones. Legacy vaults use an explicit
`upgrade` with validation against existing files. [Migration contract](../references/stable-memory.md).

## 2. Read and construct recovery packets

```mermaid
flowchart LR
    A[CLI or Python caller] --> B[MemoryStore]
    B --> C[Validate published state]
    C --> D[Lexical ranking and explicit intent]
    D --> E[Search results]
    D --> F[Whole-record byte-budget selection]
    F --> G[Recovery packet]
    G --> H[Caller inspects and decides]
    I[Compaction hook] -. reminder only .-> A
```

`search`, `get`, `inspect`, and `recover` do not write to the vault. Each operation checks
published source consistency, the registry mirror, supported note projections, and the
regenerated index. `get` can inspect an expired record by stable ID. Search and recovery
use cards, not conversation summaries that could bypass claim-level status filtering.

`current` and `historical` are caller-selected retrieval policies, not inferred time
intervals. Current mode filters declared expired cards and ranks current cards before
disputed ones. Historical mode includes all states. This is not automatic temporal
reasoning or conflict detection.

## Authority, not two databases

| Object | Responsibility |
| --- | --- |
| Complete v2 source and embedded `identity_registry` | Identity authority, including retired reservations |
| Published `.chat-distiller/distill.json` | Last published source snapshot |
| Separate registry JSON, notes, and indexes | Derived projections, checked rather than silently trusted |
| Recovery packet | A read-only selection identified by source SHA-256; not a new source of truth |
| Optional RAG evidence index | Derived candidate passages joined to claims; never a source of truth |
| Human / host agent | Semantic judgment, source inspection, and decisions about what to do next |

`claim recall` composes a byte-bounded packet from the deterministic claim brief
and an optional evidence adapter. Every evidence hit must resolve to a stored
claim; superseded evidence is excluded for `current` and labelled historical for
`historical`. The evidence index is rebuildable, and the packet records how many
candidates were stale, unlinked, unresolved or omitted rather than hiding them.

Claims carry an optional `scope` label (default `all`) and an optional
`expires_at` UTC timestamp. Scopes narrow where a decision applies: conflict
detection only fires between claims whose scopes overlap, so disjoint
environments can hold different conclusions without superseding each other.
Expiry is a read-time policy, not a status transition — a claim past its
deadline is excluded from the current brief, counted under
`counts.time_expired`, and kept in the JSONL with its chain intact. Neither
field is an enforcement mechanism: scope is a structural label the caller must
honor, and expired claims are excluded by query time, never rewritten.

The source hash identifies bytes; it is not an authenticity signature. Supported note
checks cover identity/status/type projections, not every Markdown body byte. Returned
bodies come from the source-derived index, not unchecked edits to generated Markdown.

The claim store serializes read-modify-write mutations with an in-process lock plus
an OS advisory byte lock. Contention past the timeout is an explicit `ClaimStoreBusy`
failure, not a last-writer-wins overwrite. `claim backup` writes a canonical snapshot
with a checksummed manifest; `claim restore` verifies it and preserves the current
store before replacement. `claim redact` removes content while keeping a content-free
tombstone and chain, and `claim delete` removes rows; both write a pre-change backup
(unless explicitly disabled) and an append-only audit entry. Redacted claims are
excluded from briefs, conflict detection and RAG evidence. See
[Data safety](data-safety.md).

## Storage layout

```text
<vault>/对话沉淀/
├── 会话笔记/                     # readable conversation notes
├── 知识卡片/                     # readable atomic cards
├── 知识索引.md / 知识索引.jsonl  # derived indexes
├── 操作日志.md                   # operation log, not a transaction journal
├── 00 · 对话沉淀 MOC.md / 沉淀索引.base
└── .chat-distiller/
    ├── distill.json              # published source
    ├── identity-registry.json    # checked mirror
    ├── taxonomy.md               # vocabulary owned by this vault
    └── pending/                  # hook markers, not distilled memories
```

The claim store lives separately, next to the project that owns it:

```text
<project>/.claim-ledger/
├── claims.jsonl                  # only authority
├── claims.jsonl.lock             # OS advisory lock target; left in place
├── claims.audit.jsonl            # redact / delete / restore entries, no content
└── backups/
    ├── claims-<utc>.jsonl        # canonical snapshot
    └── claims-<utc>.manifest.json
```

Core code lives under `chat_distiller/_internal`; `scripts/` contains compatible entry
points, not a second implementation. The original standalone compaction hook remains
separate. Templates are packaged for installed use; an existing vault's vocabulary is
not reset by an upgrade.

## Failure boundaries

Reads reject detected inconsistency instead of returning apparently valid results.
The claim store adds an advisory writer lock and pre-change backups, but this is not a
database transaction, hostile-filesystem defense, or crash-recovery journal; the
multi-file vault renderer remains single-writer. Repair from a consistent source or
backup; do not bypass a failed check to obtain a result.

Recovery can return `ready`, `no_match`, or `budget_exhausted`. Whole records retain
sources and states; oversized records are skipped rather than truncated. The serialized
UTF-8 budget includes metadata and a newline. [Full packet contract](memory-engine.md#recovery-packet-contract).

Memory text remains untrusted data. This component does not execute it or send it to a
model. The caller must enforce its own tool permissions and instruction boundaries.
A status flag or hash alone does not prevent prompt injection.

## Naming layers (deliberate, not drift)

The project carries three public names. This is a compatibility contract, not
unfinished migration:

| Layer | Name | Status |
| --- | --- | --- |
| Product | **ClaimLedger** | current |
| Distribution / CLI | `claim-ledger` (PyPI), `claim` command | current; `chat-distiller` remains a compatible entry point |
| Python package | `chat_distiller` | kept: importing code, the user data home `~/.chat-distiller` and the legacy command surface all pin to it |

Renaming the package would break every downstream import and the documented
data-home compatibility promise for zero behaviour gain. New modules use the
product vocabulary in docstrings; the package name stays until a v2 line
deliberately breaks compatibility. Decision recorded 2026-10-25.

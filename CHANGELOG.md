# Changelog

Package versions below describe the Python distribution, not a claim of a PyPI release
or a corresponding Git tag.

## Unreleased — governed memory v2, one-timeline demo, structural cleanup

**Engine (Phase A, all zero-model and deterministic):**
- Bitemporal claims: `valid_from` / `valid_to` real-world validity windows and an
  explicit `superseded_at` system timestamp; `brief --at` / `claims --at`
  reconstruct what the ledger believed at any instant.
- Dependency backtracking: `record --depends-on` records hard premises; a fallen
  premise surfaces dependents in the brief as unmotivated instead of settled.
- Dispute lifecycle closure: disputes record what they object to and close via
  `claim resolve --sustain | --withdraw | --text`; every outcome keeps the
  supersession chain valid.
- MCP surface aligned with the CLI: `claim_resolve`, `at` parameters on
  brief/claims, `depends_on` / validity windows on record.

**Demo:** rebuilt from seven engine views into one project timeline (what counts
now / needs you / superseded) with a Kimi-measured visual language — tokens
(type ladder, #1783ff accent, motion curves) and components (24px composer,
borderless chips) extracted from kimi.com's live stylesheet; point-in-time view,
inline conflict resolution and the Doubao→Codex handoff narrative first-class.

**Structure:** the CLI split out of the store engine (`claims_cli.py`); the
three stored statuses defined once in `status.py`; declarative `data-i18n`
bindings replace hand-updated UI strings; naming layers documented as a
compatibility decision.

## Package 0.10.0: the demo speaks Chinese — bilingual UI with a toggle (runtime 0.10.0)

- The demo interface is now bilingual (中文 / English) with a topbar toggle;
  the choice persists in localStorage and the default language is Chinese.
- Static copy is tagged with `data-i18n` anchors; every dynamic string
  (toasts, receipts, proposals, brief/context documents, search summaries,
  evidence tables, safety lists, confirm dialogs, status labels) resolves
  through a single dictionary. `document.documentElement.lang` follows the
  choice. Claim text itself is data and is never translated.
- All screenshots, the eight-frame GIF and product-page assets were recaptured
  from the Chinese default UI.

## Package 0.9.0: Kimi-inspired light redesign of the demo UI (runtime 0.9.0)

- The demo interface was redesigned from the dark terminal aesthetic to a light,
  calm system in the spirit of Moonshot Kimi: white cards on a soft gray canvas,
  hairline borders, large radii, generous whitespace and one blue-violet accent
  gradient for primary actions.
- Status colors were re-tuned for light surfaces (green current, amber disputed,
  gray superseded) while keeping the exact semantics; wire JSON stays a dark code
  block for contrast.
- All screenshots, the eight-frame GIF and the product-page assets were
  recaptured from the redesigned UI; no behavior changed anywhere.

## Package 0.8.0: general transcript import — any chat source feeds the gateway (runtime 0.8.0)

- `claim connect` now accepts three sources: `doubao` (unchanged), `generic` (the documented
  public JSONL contract: `session_id` / `role` / `content` / `timestamp`, validated in full
  before staging) and `claude-code` (Claude Code session transcripts from
  `~/.claude/projects` or an explicit `--input` directory/file).
- All three feed the identical pipeline: read-only transcript staging under
  `sources/<connector>/`, a plan-bound review bundle, host-agent distillation and context
  retrieval. `sync` stays incremental via per-session fingerprints; a source that changes
  mid-extraction is skipped, never half-committed.
- The Claude Code adapter keeps user text turns, assistant text and tool-call trails; it
  excludes `thinking` blocks, tool results, sidechain (subagent) rows and system metadata,
  and discloses the exclusions in the record's `degraded` notes.
- Wrapping any chat tool with a ten-line exporter now makes its history claim-minable.

## Package 0.7.0: scope and expiry — decisions that apply somewhere and for a while (runtime 0.7.0)

- Added an optional `scope` to every claim (`claim record --scope production`,
  MCP `claim_record`, demo form). `scope: "all"` applies everywhere; decisions in
  disjoint scopes can coexist without superseding each other, and conflict
  detection only fires when scopes overlap. Briefs and listings accept `--scope`
  and include `all`-scoped claims.
- Added an optional `expires_at` UTC timestamp (`claim record --expires-at`).
  Expiry is a read-time policy: past the deadline a claim stops counting as
  current and the brief reports it in `counts.time_expired`, but the stored row
  keeps its status and supersession chain untouched. Recording is refused for
  timestamps in the past.
- The duplicate guard now protects only the live view: identical text in a
  disjoint scope is a different decision, and re-recording an expired claim is
  the natural renewal path.
- Older stores stay valid: rows written before 0.7.0 read as `scope: "all"`,
  `expires_at: null`; no migration is required.

## Package 0.6.0: adoption path — init, PyPI readiness and a Safety view (runtime 0.6.0)

- Added `claim init`: creates an empty claim store, refuses to touch one that
  already has data, and prints the exact next commands (record, brief, MCP
  registration with the resolved store path, Skill install). This is the guided
  path from "saw the demo" to "using a real ledger".
- Added `claim backups` (snapshot list with manifest facts), `claim audit`
  (filterable redact/delete/restore log with corruption refusal) and
  `claim backup --keep N` (prune older snapshots after writing, never the fresh
  one).
- Added a **Safety** view to the demo: backup with one click, the append-only
  audit trail, and per-claim Redact/Delete actions with confirmation. Redacted
  claims render as dashed tombstones that keep their id, status and supersession
  chain. Read-only ledgers keep backup/audit available and refuse removals.
- Added the same operations over HTTP: `POST /api/backup`, `GET /api/backups`,
  `GET /api/audit`, `POST /api/redact`, `POST /api/delete` — destructive calls
  require `confirm: true`, and a read-only store answers `403` while backup and
  audit stay readable.
- Packaging metadata for PyPI: project URLs, keywords, classifiers; sdist and
  wheel both build and pass `twine check`.

## Package 0.5.0: demo, RAG context and data safety (runtime 0.5.0)

- Added `claim recall` and the MCP `claim_recall` tool: a byte-bounded composite
  packet containing the deterministic claim brief plus optional evidence from a
  host-supplied RAG index. Every evidence hit must resolve to a stored claim and
  passes the same status policy (superseded excluded for `current`, labelled
  historical for `historical`); unlinked/unknown/stale/omitted evidence is counted,
  never silently admitted. Added `JsonlEvidenceIndex`, the `EvidenceRetriever`
  protocol, a documented custom-vector-retriever seam and `docs/rag.md`. Core
  runtime dependencies remain zero; the index is derived and rebuildable.
- Added `claim index build/status`: sealing writes a header with the claim-store
  digest and a rows digest; `claim recall` refuses an index built against a
  different store. Added retriever timeout with brief-only fallback, per-claim
  evidence quota, and adaptive candidate-window widening; counters expose every
  exclusion/omission.
- Added cross-process claim-store locking: an in-process re-entrant lock plus an
  OS advisory byte lock (`flock` / `msvcrt.locking`) around every mutation. A
  timeout raises `ClaimStoreBusy` instead of a last-writer-wins overwrite; the
  lock file is left in place and the OS releases the lock on process exit.
- Added `claim backup` and `claim restore` with canonical snapshots, checksummed
  manifests, byte/digest verification, graph validation and an automatic backup
  of the current store before replacement. Added `claim redact` (content-free
  tombstone, optional chain cascade, excluded from briefs and RAG evidence) and
  `claim delete` (hard removal, explicit cascade when referenced). Both write an
  append-only audit entry and a plaintext pre-change backup by default, with
  `--no-backup` for true erasure. Added `docs/data-safety.md`.
- Added `claim suggest` and the MCP `claim_suggest` tool: a review-only proposal
  with detected conflicts, resolution guidance and status-filtered evidence. It
  never writes; `claim_record` still requires every conflict id in `supersedes`
  or an explicit dispute. MCP now exposes five tools.
- Added `benchmarks/rag/` with five structural queries over the synthetic
  scenario: status-blind evidence 2 stale hits / 75% current ratio vs
  status-aware 0 stale hits / 100% current ratio at 100% expected coverage. It
  is explicitly labelled structural, not semantic entailment or answer quality.
- Added `claim demo`: a zero-dependency stdlib HTTP server and a static browser UI over
  the real `ClaimStore`. The demo renders the ledger, refuses conflicting writes with
  the real lexical matcher, resolves them through explicit supersession or dispute,
  renders byte-budgeted briefs, compares status-aware with status-blind search, and
  reads the checked-in benchmark reports. It seeds a synthetic Atlas API scenario into
  a disposable temp store; `--store` binds an existing ledger read-only by default,
  never seeds it implicitly, and keeps Reset disabled (`--write` opts into recording;
  `--seed` with `--write` explicitly seeds an empty bound store). Added a **Context**
  view that builds the same brief + evidence packet over HTTP, toggles `current` /
  `historical` intent, exposes every exclusion counter and the exact wire JSON, and a
  review-only **Preview proposal** panel that reveals conflicts and linked
  evidence without writing. The synthetic evidence index now ships in both the
  checkout and the installed package.
- A write that overlaps several current claims can supersede all detected conflicts
  together (`supersedes` accepts a string or a list). Partial resolution is refused
  instead of leaving the new current claim in silent coexistence. Status filters also
  accept the English aliases `current` / `superseded` / `disputed`.
- The demo's status-blind comparison now orders equal scores newest-first; the stale
  result is demonstrated with `use sqlite`, where it is the genuine top lexical match
  rather than a tie-break artifact. The record view is read-only and explains how to
  opt into writes when a real store is bound.
- Added `chat_distiller.demo` with `python -m chat_distiller.demo`; package data now
  includes the static UI and the synthetic evidence index. No runtime dependency was
  added.
- Added a bilingual static product page in `site/` with a GitHub Pages workflow, a
  20-second seven-frame GIF and social preview built by `tools/build_demo_gif.py`, and
  a presenter script in `SHOWCASE.md` / `docs/demo.md`.
- Portability: Wiki exports and captured CLI receipts now write LF bytes on every
  platform so manifest and packet byte counts match; the Skill installer retries
  transient Windows directory-sharing errors; MCP tests use a reader thread instead
  of `select()` on pipes; README verification translates Git Bash temp paths. The
  suite is 399 tests, green on this Windows checkout (2 platform-specific skips), and
  `tools/verify_docs.py` passes against a clean wheel install.

## Unreleased: renamed to ClaimLedger (runtime 0.4.0)

- Repository, distribution and Skill are now ClaimLedger (`claim-ledger`); the CLI gains `claim`
  as the primary entry while `carrytrace` and `chat-distiller` remain permanent aliases with
  unchanged semantics. The `chat_distiller` import name is kept until the P1 storage merge.
- MCP tools are renamed claim_brief / claim_record / claim_claims; the project-scoped claim store
  defaults to `.claim-ledger/claims.jsonl` (`CLAIM_LEDGER_STORE`, with `CARRYTRACE_STORE` honored).
- Internal install markers (`.carrytrace-skill-lock`, `.carrytrace-skill-backups`,
  `.carrytrace-managed.json`) intentionally keep their names so existing managed installs remain
  managed. Historical entries below are verbatim.

## Unreleased: MCP stdio delivery for the claim store (runtime 0.4.0)

- Added `carrytrace mcp`: a zero-dependency MCP stdio server (line-delimited JSON-RPC 2.0) exposing
  `carrytrace_brief` / `carrytrace_record` / `carrytrace_claims` as tools. The store is bound at
  launch (`--store` or `CARRYTRACE_STORE`); tools cannot address arbitrary paths. Tool failures are
  returned as `isError` results the calling agent can read and resolve; store is unchanged.
- The installed Skill now instructs hosts: read the brief before acting on prior decisions, record
  one claim at the moment a decision settles, and resolve reported conflicts explicitly instead of
  bypassing them.
- 9 protocol tests over a real subprocess; suite at 313, green. No new dependencies; no data migration.

## Unreleased: claim pipeline MVP — record / brief (runtime 0.4.0)

- Added `ClaimStore` with `record` / `brief` / `claims` on both CLI entry points: claims are
  captured in situ at decision time; a possible lexical conflict refuses silent coexistence and
  requires an explicit `--supersedes <id>` or `--dispute`; briefs render a byte-bounded snapshot
  (disputes first, current claims by topic, recent supersessions).
- The store is a strict JSONL file validated on every read; a corrupt line refuses service with its
  line number. Default location is project-scoped `.carrytrace/claims.jsonl`; deterministic
  conflict matching surfaces overlap but never judges semantics.
- Design addendum v2 ([docs/refactor-design.md](docs/refactor-design.md) §9): capture-first
  reorders the roadmap — P2 source parsing is demoted to backfill, MCP promoted to primary
  delivery. 15 new tests; suite at 304, green on macOS and Linux.

## Unreleased: maintenance handover and refactor program (runtime 0.4.0)

- Added the v1 refactor design ([docs/refactor-design.md](docs/refactor-design.md)): storage inversion
  toward a single JSONL authority, identity collapse, a thin apply protocol, declarative source
  profiles (claude_code / codex / generic_jsonl) and optional reranker/MCP delivery.
- P0 hygiene: resolved macOS `/tmp` symlink comparisons in brand-migration tests; added macOS to the
  CI test matrix; documented the structured/raw packet budget split.
- Redesigned the bilingual README around the refactor roadmap; executable examples and metric tables
  are unchanged and still executed by `verify_docs.py`.
- Runtime stays 0.4.0: no data migration, no new dependencies, all entry points and data homes compatible.

## Unreleased: CarryTrace brand migration (runtime 0.4.0)

- New CarryTrace identity, theme-aware vector artwork, bilingual Skill-first homepage and canonical repository links.
- Added `carrytrace` CLI; preserved `chat-distiller`, `chat_distiller`, existing environment names and data homes.
- New `carrytrace` Skill bundle and deterministic ZIP; legacy bundle remains available for compatibility.
- Explicit preview-first legacy migration keeps original instruction files outside host discovery, rejects edits/symlinks/duplicates and retains failed rollback evidence.
- Scope is branding and installation, not a new memory model or evidence of live host activation. No PyPI rename or v0.5 stable release.

## Unreleased: Skill-first pilot on package 0.4.0

- Added a portable Agent Skills-compatible bundle that guides source-linked context recovery,
  historical decision audits, cross-host handoff and authorized Generic JSONL extraction.
- Added local CLI skill install/status for Codex and Claude Code, user and project scopes.
- Added deterministic portable ZIP export for other clients that accept Agent Skills bundles; no
  claim of universal host activation or local CLI access from cloud environments.
  The managed installer is idempotent and refuses to overwrite foreign or modified skills.
- Added source and installed-wheel packaging checks; no new runtime dependencies.
- Existing Memory Engine, Knowledge Wiki, source adapters, benchmarks and publication
  authority are unchanged. No real host-agent activation, model-quality or auto-import
  improvement is claimed.

## Package 0.4.0: Context Gateway

- Added the simple `connect`, `sync`, `context`, and `status` surface for Doubao Work.
- Added automatic local session discovery, managed context home, content fingerprints, incremental extraction, and raw-session fallback context.
- Added plan-bound host-agent publication with stale-plan rejection and explicit retirement guards.
- Kept semantic distillation outside deterministic code; `sync` makes pending work visible rather than inventing memory.
- Added synthetic Gateway integration tests and an executed CLI experiment for source read-only behavior, no-op idempotence, byte budget, degraded input, and stale proposals.
- Kept legacy CLI, atomic memory schema 2, Knowledge Wiki, and frozen retrieval benchmarks compatible. No daemon, MCP, automatic LLM distillation, or PyPI publication is claimed.

## Package 0.3.0: Knowledge Wiki

- Added optional `KnowledgeStore` and `wiki` commands without changing atomic memory schema 2.
- Added cited proposals, scoped status validation, stable knowledge IDs, revision history and navigation links.
- Added conservative whole-source staleness checks, layered byte-bounded recovery and explicit Markdown exports.
- Added exclusive writer locks, revision guards and one-file compiled-state publication with failure tests.
- Added research/design notes, host synthesis workflow, a 16-command installed demo and CompileBench engineering experiments.
- Kept the old retrieval benchmark and legacy recovery packet unchanged. No automatic LLM accuracy claim or PyPI publication.

## Documentation and onboarding (2026-10-06)

- Rebuilt the homepage around the use case, a safe first run, evidence, and integration.
- Added an English README and a synchronized Chinese edition.
- Added a handwritten database-decision fixture and a generated, execution-checked demo.
- Added a documentation map, architecture/trust boundaries, ingestion guide, and contribution instructions.
- Added checks for local links, bilingual example parity, installed README commands, and generated demo drift.
- Kept the memory engine, schema, lexical algorithm, and frozen benchmark unchanged.

## Package 0.2.0: Memory Engine

Delivered in [PR #1](https://github.com/Anhao1314/chat-distiller/pull/1), merged 2026-10-06 (UTC+08:00).

- Packaged the existing implementation with a unified CLI and compatible script entry points.
- Added read-only `MemoryStore.search/get/inspect/recover`.
- Added complete-record recovery packets bounded by canonical UTF-8 JSON bytes.
- Rejected rendered-note status/kind projection drift in old and new query paths.
- Verified 137 source tests and 16 installed-wheel checks; retained the original benchmark scores.

See the [verification ledger](docs/verification.md) for evidence and limits.

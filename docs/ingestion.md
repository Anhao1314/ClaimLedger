# Ingestion and migration

[English quick start](../README.md#quick-start) · [中文快速体验](../README.md#quick-start)

The homepage demo starts from **handwritten synthetic cards** to make the first run
self-contained. Real ingestion includes a separate human/agent judgment step:

```text
Read-only extraction → semantic judgment → explicit identity registration → render → validate
```

## Try extraction with the same synthetic example

After the quick start, retain the activated environment and `DEMO_DIR`. These commands
extract the bundled messages and lint the already rendered cards against their transcripts:

<!-- verify:ingestion -->
```bash
chat-distiller extract --source generic_jsonl --input examples/recovery/messages.jsonl --out "$DEMO_DIR/staging"
chat-distiller lint --vault "$DEMO_DIR/vault" --transcripts "$DEMO_DIR/staging/transcripts" > "$DEMO_DIR/lint.json"
python -m json.tool "$DEMO_DIR/lint.json"
```

Both the messages and cards are synthetic. The old card's expired status and successor
were authored explicitly after the later decision; no program inferred them. The v1
fixture uses an exact display filename for its successor, which `init` resolves into a
stable ID. Existing v2 data must use stable IDs, not title matching.

## Bring your own conversations

Use `extract --source generic_jsonl --input messages.jsonl --out staging`, or
`extract --sessions-root /path/to/.sessions --out staging` for Doubao Work. Paths here
are placeholders; choose only sources you are authorized to process. Extraction reads
source caches without modifying them. [Supported input formats](../references/source-format.md).

A human or host agent then reads the transcripts and writes cards following the
[distillation schema](../references/distillation-schema.md) and vault-owned vocabulary.
The package has no automatic `distill` command. Do not replace this step with arbitrary
summaries and present the output as verified knowledge. T2 literal evidence checks flag
suspicion; they do not establish truth or validate every semantic claim.

## Choose the correct identity path

| Starting point | Path |
| --- | --- |
| New source, new vault | `migrate --mode init`, then `render` |
| Existing legacy vault | Back up; `migrate --mode upgrade --vault …`; inspect report before rendering |
| Existing v2 vault, new cards | Preserve complete identity history; `migrate --mode register`; render explicitly |
| Existing v2 vault, package update only | No data migration required for package 0.10.0 |

Do not initialize fresh identities over an existing vault. Use `--dry-run` to inspect
registration/render plans, but persist the real run before using its UUIDs: preview
identities are not final. Read [stable identity and migration](../references/stable-memory.md)
for exact commands and conflict handling. Generated Markdown is not the canonical edit
surface; edit the source and render after resolving consistency errors.

## Consume existing memory

Use `chat-distiller search`, `get`, `inspect`, or `recover`, or the read-only `MemoryStore`
API. A missing vault is an error, not an invitation to create one. For historical analysis,
pass `--intent historical`; older records retain their states and successor links.
The original `python3 scripts/*.py` commands remain supported from a checkout.

## Privacy and hooks

Use synthetic examples for public issues and demos. Do not commit personal transcripts,
API credentials, private file paths, or generated real-user vaults to this public repository.
Installation from source may download build tooling; the memory tools do not require a
remote model service. A host agent's own data handling is outside this package.

[Hook templates](../references/hooks.example.json) show reminder events, not a validated
integration with every host version. `PreCompact` leaves a pending marker;
`SessionStart(compact)` reminds the agent to query. Neither event automatically distills
memory or injects a recovery packet. [Host-agent workflow](../SKILL.md).

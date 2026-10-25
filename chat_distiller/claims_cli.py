"""Command-line surface for the claim store: record, resolve, brief, claims.

Split from chat_distiller/claims.py so the store engine stays importable
without argparse. The unified `claim` entry point dispatches here via
chat_distiller.cli; behaviour is unchanged.
"""
import argparse
import json
import sys

from .claims import (
    DEFAULT_MAX_BYTES, ClaimStore, ClaimStoreError,
    STATUS_CURRENT,
)
from .context import (
    DEFAULT_CONTEXT_BYTES, JsonlEvidenceIndex, build_context, serialize_context, suggest_claim,
)
from .recovery import serialize_packet


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="claim-ledger", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_cmd = commands.add_parser("init", help="create an empty claim store and print next steps")
    init_cmd.add_argument("--store")
    init_cmd.add_argument("--json", action="store_true")

    record = commands.add_parser("record", help="capture one claim at decision time")
    record.add_argument("text")
    record.add_argument("--topic", default="general")
    record.add_argument("--tag", action="append", default=[])
    record.add_argument("--supersedes", action="append", default=[],
                        help="claim_id replaced by this claim; repeat for multiple conflicts")
    record.add_argument("--dispute", action="store_true",
                        help="record as disputed; also resolves a detected conflict without superseding")
    record.add_argument("--source")
    record.add_argument("--quote")
    record.add_argument("--session", dest="session_hint")
    record.add_argument("--scope", help="where the claim applies, e.g. production (default: all)")
    record.add_argument("--expires-at", dest="expires_at",
                        help="UTC timestamp after which the claim no longer counts as current")
    record.add_argument("--valid-from", dest="valid_from",
                        help="UTC timestamp the decision started being true (default: now)")
    record.add_argument("--valid-to", dest="valid_to",
                        help="UTC timestamp the decision stopped being true; backdating is allowed")
    record.add_argument("--depends-on", dest="depends_on", action="append", default=[],
                        help="claim_id this decision relies on; a fallen premise flags it for review")
    record.add_argument("--store")
    record.add_argument("--json", action="store_true")

    resolve_cmd = commands.add_parser("resolve", help="close a recorded dispute")
    resolve_cmd.add_argument("claim_id")
    outcomes = resolve_cmd.add_mutually_exclusive_group(required=True)
    outcomes.add_argument("--sustain", action="store_true",
                          help="the objection wins: it becomes current and supersedes its targets")
    outcomes.add_argument("--withdraw", action="store_true",
                          help="the objection is retracted in favour of the standing claim")
    outcomes.add_argument("--text",
                          help="a new decision that supersedes both the dispute and its targets")
    resolve_cmd.add_argument("--topic")
    resolve_cmd.add_argument("--tag", action="append", default=[])
    resolve_cmd.add_argument("--source")
    resolve_cmd.add_argument("--quote")
    resolve_cmd.add_argument("--session", dest="session_hint")
    resolve_cmd.add_argument("--scope")
    resolve_cmd.add_argument("--store")
    resolve_cmd.add_argument("--json", action="store_true")

    brief = commands.add_parser("brief", help="render the current-state brief within a byte budget")
    brief.add_argument("--store")
    brief.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    brief.add_argument("--topic")
    brief.add_argument("--scope", help="restrict the brief to claims that apply to this scope")
    brief.add_argument("--at",
                       help="reconstruct the brief at a past UTC instant, e.g. 2026-03-01T00:00:00Z")
    brief.add_argument("--compact", action="store_true", help="omit indentation")

    listing = commands.add_parser("claims", help="list or search claims")
    listing.add_argument("--store")
    listing.add_argument("--status", default=STATUS_CURRENT)
    listing.add_argument("--topic")
    listing.add_argument("--query")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--at",
                         help="filter by status at a past UTC instant; requires an explicit --status")
    listing.add_argument("--include-redacted", action="store_true",
                         help="include content-free redaction tombstones")

    backup = commands.add_parser("backup", help="write a verified snapshot and manifest")
    backup.add_argument("--store")
    backup.add_argument("--out", help="backup directory (default: <store>/backups)")
    backup.add_argument("--keep", type=int,
                        help="after writing, delete older snapshots beyond this many")
    backup.add_argument("--json", action="store_true")

    listing_backups = commands.add_parser("backups", help="list snapshots and manifests")
    listing_backups.add_argument("--store")

    audit = commands.add_parser("audit", help="inspect the redact/delete/restore audit log")
    audit.add_argument("--store")
    audit.add_argument("--limit", type=int, default=50)
    audit.add_argument("--action", choices=["redact", "delete", "restore"])
    audit.add_argument("--json", action="store_true")

    restore = commands.add_parser("restore", help="verify and restore a backup snapshot")
    restore.add_argument("--from", dest="backup_path", required=True)
    restore.add_argument("--store")
    restore.add_argument("--yes", action="store_true",
                         help="replace a non-empty destination store")
    restore.add_argument("--allow-unverified", action="store_true",
                         help="allow a raw JSONL backup without a manifest")
    restore.add_argument("--backup-dir")
    restore.add_argument("--json", action="store_true")

    redact = commands.add_parser(
        "redact", help="remove claim content in place while keeping identity and history")
    redact.add_argument("claim_id")
    redact.add_argument("--store")
    redact.add_argument("--cascade", action="store_true",
                        help="redact the whole supersession chain")
    redact.add_argument("--backup-dir")
    redact.add_argument("--no-backup", action="store_true",
                        help="do not retain a plaintext pre-redaction copy")
    redact.add_argument("--yes", action="store_true", help="confirm content destruction")
    redact.add_argument("--json", action="store_true")

    delete = commands.add_parser(
        "delete", help="permanently delete a claim, or its supersession chain")
    delete.add_argument("claim_id")
    delete.add_argument("--store")
    delete.add_argument("--cascade", action="store_true",
                        help="delete every claim in the supersession chain")
    delete.add_argument("--backup-dir")
    delete.add_argument("--no-backup", action="store_true",
                        help="do not retain a plaintext pre-deletion copy")
    delete.add_argument("--yes", action="store_true", help="confirm permanent deletion")
    delete.add_argument("--json", action="store_true")

    recall = commands.add_parser(
        "recall", help="brief + optional status-filtered RAG evidence in one packet")
    recall.add_argument("--query", required=True)
    recall.add_argument("--store")
    recall.add_argument("--evidence", help="optional JSONL evidence index (or use the Python API)")
    recall.add_argument("--max-bytes", type=int, default=DEFAULT_CONTEXT_BYTES)
    recall.add_argument("--intent", choices=["current", "historical"], default="current")
    recall.add_argument("--top-k", type=int, default=8)
    recall.add_argument("--max-per-claim", type=int, default=2,
                        help="maximum evidence chunks retained per claim (default 2)")
    recall.add_argument("--timeout", type=float, default=5.0,
                        help="seconds before the evidence adapter falls back to brief-only")
    recall.add_argument("--compact", action="store_true", help="emit the canonical wire packet")

    suggest = commands.add_parser(
        "suggest", help="propose a claim for review; never writes to the store")
    suggest.add_argument("--text", required=True)
    suggest.add_argument("--topic", default="general")
    suggest.add_argument("--tag", action="append", default=[])
    suggest.add_argument("--query", help="evidence query; defaults to the proposed text")
    suggest.add_argument("--store")
    suggest.add_argument("--evidence", help="optional JSONL evidence index")
    suggest.add_argument("--top-k", type=int, default=8)
    suggest.add_argument("--max-per-claim", type=int, default=2)
    suggest.add_argument("--timeout", type=float, default=5.0)

    index = commands.add_parser("index", help="seal or inspect a JSONL evidence index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    index_build = index_commands.add_parser("build", help="seal a source index to one claim store")
    index_build.add_argument("--source", required=True)
    index_build.add_argument("--out", required=True)
    index_build.add_argument("--store", required=True)
    index_status = index_commands.add_parser("status", help="check index freshness and integrity")
    index_status.add_argument("--evidence", required=True)
    index_status.add_argument("--store")

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            result = ClaimStore(args.store).record(
                args.text, topic=args.topic, tags=args.tag, supersedes=args.supersedes or None,
                dispute=args.dispute, source=args.source,
                quote=args.quote, session_hint=args.session_hint,
                scope=args.scope, expires_at=args.expires_at,
                valid_from=args.valid_from, valid_to=args.valid_to,
                depends_on=args.depends_on or None)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                recorded = result["recorded"]
                line = f"recorded {recorded['claim_id']} [{recorded['status']}] topic={recorded['topic']}"
                if recorded.get("scope", "all") != "all":
                    line += f" scope={recorded['scope']}"
                if recorded.get("expires_at"):
                    line += f" expires_at={recorded['expires_at']}"
                if recorded.get("valid_from"):
                    line += f" valid_from={recorded['valid_from']}"
                if recorded.get("valid_to"):
                    line += f" valid_to={recorded['valid_to']}"
                if result["superseded_claims"]:
                    line += " superseded=" + ",".join(result["superseded_claims"])
                if result["conflicts_with"]:
                    line += f" conflicts_with={','.join(result['conflicts_with'])}"
                print(line)
        elif args.command == "resolve":
            outcome = ("sustain" if args.sustain else
                       "withdraw" if args.withdraw else "supersede")
            result = ClaimStore(args.store).resolve(
                args.claim_id, outcome=outcome, text=args.text, topic=args.topic,
                tags=args.tag, source=args.source, quote=args.quote,
                session_hint=args.session_hint, scope=args.scope)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                line = f"resolved {result['dispute']} outcome={result['outcome']}"
                if result["superseded_claims"]:
                    line += " superseded=" + ",".join(result["superseded_claims"])
                if result.get("recorded"):
                    line += f" as {result['recorded']['claim_id']}"
                print(line)
        elif args.command == "brief":
            packet = ClaimStore(args.store).brief(max_bytes=args.max_bytes, topic=args.topic,
                                                  scope=args.scope, at=args.at)
            if args.compact:
                print(serialize_packet(packet), end="")
            else:
                print(json.dumps(packet, ensure_ascii=False, indent=2))
        elif args.command == "recall":
            evidence = JsonlEvidenceIndex(args.evidence) if args.evidence else None
            packet = build_context(
                ClaimStore(args.store), args.query, max_bytes=args.max_bytes,
                intent=args.intent, retriever=evidence, top_k=args.top_k,
                max_per_claim=args.max_per_claim, retriever_timeout=args.timeout)
            if args.compact:
                print(serialize_context(packet), end="")
            else:
                print(json.dumps(packet, ensure_ascii=False, indent=2))
        elif args.command == "suggest":
            evidence = JsonlEvidenceIndex(args.evidence) if args.evidence else None
            proposal = suggest_claim(
                ClaimStore(args.store), args.text, topic=args.topic, tags=args.tag,
                query=args.query, retriever=evidence, top_k=args.top_k,
                max_per_claim=args.max_per_claim, retriever_timeout=args.timeout)
            print(json.dumps(proposal, ensure_ascii=False, indent=2))
        elif args.command == "index":
            if args.index_command == "build":
                index = JsonlEvidenceIndex(args.source)
                result = index.seal(args.out, ClaimStore(args.store).digest())
            else:
                index = JsonlEvidenceIndex(args.evidence)
                digest = ClaimStore(args.store).digest() if args.store else None
                result = index.status(digest)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        elif args.command == "init":
            result = ClaimStore(args.store).init()
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"store ready: {result['store']}" + ("" if result["created"] else " (already existed, empty)"))
                for step in result["next_steps"]:
                    print("  " + step)
        elif args.command == "backups":
            result = ClaimStore(args.store).backups()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "audit":
            result = ClaimStore(args.store).audit_entries(limit=args.limit, action=args.action)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"audit log: {result['path']} ({result['total']} entries)")
                for entry in result["entries"]:
                    actor = entry.get("actor") or "-"
                    backup_name = entry.get("backup_file") or "-"
                    print(f"{entry['at']} {entry['action']:<8} {','.join(entry['claim_ids'])} "
                          f"actor={actor} backup={backup_name}")
        elif args.command == "backup":
            result = ClaimStore(args.store).backup(args.out, keep=args.keep)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"backup {result['path']} ({result['claims']} claims, sha256 {result['file_sha256'][:12]}…)")
                if result.get("pruned"):
                    print("pruned: " + ", ".join(result["pruned"]))
        elif args.command == "restore":
            result = ClaimStore(args.store).restore(
                args.backup_path, overwrite=args.yes,
                allow_unverified=args.allow_unverified, backup_dir=args.backup_dir)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"restored {result['claims']} claims from {result['restored']}")
        elif args.command in ("redact", "delete"):
            if not args.yes:
                raise ClaimStoreError(
                    f"{args.command} is destructive; pass --yes to confirm")
            store = ClaimStore(args.store)
            operation = getattr(store, args.command)
            result = operation(
                args.claim_id, cascade=args.cascade,
                keep_backup=not args.no_backup, backup_dir=args.backup_dir)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif result.get("already_redacted"):
                print(f"claim {args.claim_id} is already redacted")
            else:
                verb = "redacted" if args.command == "redact" else "deleted"
                suffix = (f"backup {result['backup']['path']}"
                          if result.get("backup") else "no backup retained")
                print(f"{verb} {','.join(result['claim_ids'])}; {suffix}")
        else:
            if args.limit < 1 or args.limit > 1000:
                raise ClaimStoreError("limit must be between 1 and 1000")
            rows = ClaimStore(args.store).claims(
                status=args.status, topic=args.topic, query=args.query,
                include_redacted=args.include_redacted, at=args.at)
            print(json.dumps({"ok": True, "count": len(rows),
                              "claims": rows[:args.limit]}, ensure_ascii=False, indent=2))
        return 0
    except (ClaimStoreError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

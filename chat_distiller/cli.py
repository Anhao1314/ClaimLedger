"""Unified CLI. Legacy write commands preserve their original contracts."""
import argparse
import importlib
import json
import sys

from .store import MemoryStore, MemoryIntegrityError, MemoryNotFoundError
from .recovery import serialize_packet

LEGACY = {
    "extract": "extract_sessions", "migrate": "migrate_memory",
    "render": "render_notes", "lint": "lint_notes",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main(argv[1:])
    if argv and argv[0] in {
            "init", "record", "resolve", "brief", "claims", "recall", "suggest", "index",
            "backup", "backups", "audit", "restore", "redact", "delete"}:
        from .claims import main as claims_main
        return claims_main(argv)
    if argv and argv[0] in {"connect", "sync", "context", "status"}:
        from .gateway.cli import main as gateway_main
        return gateway_main(argv)
    if argv and argv[0] == "wiki":
        from .wiki.cli import main as wiki_main
        return wiki_main(argv[1:])
    if argv and argv[0] == "skill":
        from .skill_installer import main as skill_main
        return skill_main(argv[1:])
    if argv and argv[0] == "demo":
        from .demo.server import main as demo_main
        return demo_main(argv[1:])
    if argv and argv[0] in LEGACY:
        implementation = importlib.import_module("._internal." + LEGACY[argv[0]], "chat_distiller")
        previous = sys.argv
        try:
            sys.argv = ["chat-distiller " + argv[0]] + argv[1:]
            return implementation.main() or 0
        finally:
            sys.argv = previous
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="chat-distiller 0.10.0")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("search", "get", "inspect", "recover"):
        sub = commands.add_parser(name)
        sub.add_argument("--vault", required=True)
        sub.add_argument("--subdir", default="对话沉淀")
        if name in ("search", "recover"):
            sub.add_argument("--query", required=True)
            sub.add_argument("--top-k", type=int, default=5)
            sub.add_argument("--intent", choices=["current", "historical"], default="current")
        if name == "search":
            sub.add_argument("--kind")
            sub.add_argument("--category")
        if name == "recover":
            sub.add_argument("--max-bytes", type=int, default=8192)
        if name == "get":
            sub.add_argument("--id", required=True)
    commands.add_parser("wiki", help="compile and query evidence-linked knowledge pages")
    commands.add_parser("skill", help="install or inspect the portable Agent Skill")
    commands.add_parser("init", help="create an empty claim store and print next steps")
    commands.add_parser("record", help="capture one claim at decision time")
    commands.add_parser("resolve", help="close a recorded dispute")
    commands.add_parser("brief", help="render a byte-bounded current-state brief")
    commands.add_parser("claims", help="list or search captured claims")
    commands.add_parser("recall", help="brief plus optional status-filtered RAG evidence")
    commands.add_parser("suggest", help="propose a claim for review without writing")
    commands.add_parser("index", help="seal or inspect a RAG evidence index")
    commands.add_parser("backup", help="write a verified claim-store snapshot")
    commands.add_parser("backups", help="list claim-store snapshots and manifests")
    commands.add_parser("audit", help="inspect redact/delete/restore audit entries")
    commands.add_parser("restore", help="verify and restore a claim-store snapshot")
    commands.add_parser("redact", help="remove claim content while preserving identity")
    commands.add_parser("delete", help="permanently delete a claim or its chain")
    commands.add_parser("mcp", help="serve the claim store over MCP stdio")
    commands.add_parser("demo", help="run the local browser demo (zero dependencies)")
    for name in LEGACY:
        commands.add_parser(name, help="delegate to compatible " + LEGACY[name] + " command")
    args = parser.parse_args(argv)
    try:
        store = MemoryStore(args.vault, args.subdir)
        if args.command == "recover":
            packet = store.recover(args.query, top_k=args.top_k, intent=args.intent, max_bytes=args.max_bytes)
            sys.stdout.write(serialize_packet(packet))
            return 0
        if args.command == "search":
            result = {"ok": True, "results": store.search(args.query, top_k=args.top_k, intent=args.intent,
                                                          kind=args.kind, category=args.category)}
        elif args.command == "get":
            result = {"ok": True, "memory": store.get(args.id)}
        else:
            result = store.inspect()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (MemoryIntegrityError, MemoryNotFoundError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__, "results": []}, ensure_ascii=False))
        return 1

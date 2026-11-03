"""MCP stdio server exposing the Jev-first memory layer.

Zero dependencies: newline-delimited JSON-RPC 2.0 on stdin/stdout, diagnostics
on stderr only. All files live in one directory (--dir, default ~/.jev-memory
or JEV_MEMORY_DIR):

    records.jsonl    append-only, hash-chained records (no stored status)
    judgments.jsonl  sealed judgment log (hash-chained)
    cache.jsonl      judgment cache (derived, deletable)
    outcomes.jsonl   human verdicts (hash-chained)

Tools: memory_record, memory_decide, memory_brief, memory_outcome,
memory_calibrate, memory_audit.

Consent: memory_decide/brief call the judgment provider, which needs
TYPESAFE_API_KEY in the environment. Launching this server with that key set
IS the consent decision — record text will leave the machine. Without the
key those tools still answer, in degraded mode: every record is review, the
result says so, and nothing is admitted.

Tool failures are returned as isError results so the calling agent can see
and resolve them; only protocol violations produce JSON-RPC errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .audit import for_record, summarize
from .calibration import calibrate
from .cache import Cache
from .contracts import ContractError
from .judge import DEFAULT_BUDGET_BYTES, judge
from .log import append_judgment, read as read_log, verify as verify_log
from .outcomes import append_outcome, read as read_outcomes, verify as verify_outcomes
from .records import RecordStore, find_near_duplicate
from .select import select_candidates

SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
FALLBACK_VERSION = "2025-06-18"
SERVER_NAME = "jev-memory"
SERVER_VERSION = "0.1.0"
MAX_LIMIT = 6


class MethodError(Exception):
    """A JSON-RPC protocol error that must carry a code back to the client."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {"name": "memory_record",
         "description": (
             "Append ONE decision or constraint to project memory at the moment it is "
             "settled. Text must stand alone. Exact duplicates are refused; a "
             "paraphrase of an existing record returns that record with "
             "created=false instead of appending. Records carry no status: "
             "whether a record still holds is decided later by the judge."),
         "inputSchema": {"type": "object", "properties": {
             "text": {"type": "string", "description": "one standalone statement"},
             "source": {"type": "string", "description": "who wrote it (agent, tool, human)"},
             "scope": {"type": "string", "description": "optional scope label"}},
             "required": ["text", "source"]}},
        {"name": "memory_decide",
         "description": (
             "Select candidate records for a task and judge them: one admit choice per "
             "record, pairwise conflict localization, governing. Seals the judgment "
             "and returns its hash; pass that hash to memory_outcome. Requires "
             "TYPESAFE_API_KEY; without it the result is degraded and every "
             "record is review."),
         "inputSchema": {"type": "object", "properties": {
             "task": {"type": "string"},
             "scope": {"type": "string"},
             "limit": {"type": "integer", "description": "candidate cap, 1..6, default 6"},
             "budget_bytes": {"type": "integer", "default": 2048}},
             "required": ["task"]}},
        {"name": "memory_brief",
         "description": ("The agent-facing text projection only: admitted constraints, "
                         "needs-review records, unresolved conflicts. Same decision as "
                         "memory_decide, sealed to the log with a returned hash; served "
                         "from cache when possible."),
         "inputSchema": {"type": "object", "properties": {
             "task": {"type": "string"}, "scope": {"type": "string"},
             "limit": {"type": "integer"}, "budget_bytes": {"type": "integer"}},
             "required": ["task"]}},
        {"name": "memory_outcome",
         "description": ("Record how a sealed judgment turned out for one record: upheld, "
                         "overturned, or unclear. Human input only — outcomes are the only "
                         "input the calibration view trusts."),
         "inputSchema": {"type": "object", "properties": {
             "record_id": {"type": "string"},
             "verdict": {"type": "string",
                         "enum": ["upheld", "overturned", "unclear"]},
             "by": {"type": "string"},
             "note": {"type": "string"},
             "judgment_hash": {"type": "string",
                               "description": "omit to attach to the newest judgment touching this record"}},
             "required": ["record_id", "verdict", "by"]}},
        {"name": "memory_calibrate",
         "description": ("Score the judge against recorded outcomes: per-bucket upheld "
                         "rates and Brier score for admitted records."),
         "inputSchema": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ["admit"], "default": "admit"}}}},
        {"name": "memory_audit",
         "description": ("Decision history: summary counts, or per-record view when "
                         "record_id is given."),
         "inputSchema": {"type": "object", "properties": {
             "record_id": {"type": "string"}}}},
    ]


class MemoryServer:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.store = RecordStore(self.directory / "records.jsonl")
        self.log_path = self.directory / "judgments.jsonl"
        self.cache = Cache(self.directory / "cache.jsonl")
        self.outcomes_path = self.directory / "outcomes.jsonl"

    # ---- tool dispatch -----------------------------------------------------

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        handlers = {
            "memory_record": self._tool_record,
            "memory_decide": self._tool_decide,
            "memory_brief": self._tool_brief,
            "memory_outcome": self._tool_outcome,
            "memory_calibrate": self._tool_calibrate,
            "memory_audit": self._tool_audit,
        }
        if name not in handlers:
            raise MethodError(-32602, f"unknown tool: {name}")
        return handlers[name](dict(arguments or {}))

    def _tool_record(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        text = str(args["text"])
        source = str(args["source"])
        scope = args.get("scope")
        records = self.store.load()
        existing = find_near_duplicate(records, text, scope=scope)
        if existing:
            record, similarity = existing
            return {"record": record, "created": False, "duplicate": "near",
                    "similarity": similarity, "total_records": len(records),
                    "note": "a near-identical decision already exists; not appended"}
        record = self.store.append(text, source, scope=scope)
        return {"record": record, "created": True,
                "total_records": len(records) + 1}

    def _decide(self, args: Mapping[str, Any]) -> tuple:
        task = str(args["task"]).strip()
        if not task:
            raise MethodError(-32602, "task must be a non-empty string")
        limit = max(1, min(int(args.get("limit", MAX_LIMIT)), MAX_LIMIT))
        budget = int(args.get("budget_bytes", DEFAULT_BUDGET_BYTES))
        records = self.store.load()
        if not records:
            raise MethodError(-32602, "the record store is empty")
        candidates, stats = select_candidates(records, task,
                                              scope=args.get("scope"),
                                              limit=limit)
        if not candidates:
            raise MethodError(-32602, "no candidates in scope for this task")
        judgment = judge(task, candidates, budget_bytes=budget,
                         on_error="review", cache=self.cache)
        return replace(judgment, selection=stats), stats

    def _tool_decide(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        from .brief import render_brief
        judgment, stats = self._decide(args)
        sealed = append_judgment(self.log_path, judgment.to_dict())
        brief = render_brief(judgment)
        payload = {
            "brief": brief["text"],
            "admitted": brief["admitted"],
            "warnings": brief["warnings"],
            "conflicts": brief["conflicts"],
            "degraded": judgment.degraded,
            "model": judgment.model,
            "judgment_hash": sealed["judgment_hash"],
            "actions": {e.record_id: {"action": e.action, "p_admit": e.p_admit,
                                      "governing": e.governing,
                                      "conflicted": e.conflicted,
                                      "low_margin": e.low_margin}
                        for e in judgment.entries},
            "selection": stats,
            "note": ("degraded: judgment provider unreachable — every record is "
                     "review; do not act without human confirmation"
                     if judgment.degraded else None),
        }
        return {k: v for k, v in payload.items() if v is not None}

    def _tool_brief(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        from .brief import render_brief
        judgment, stats = self._decide(args)
        sealed = append_judgment(self.log_path, judgment.to_dict())
        brief = render_brief(judgment)
        return {"brief": brief["text"], "bytes": brief["bytes"],
                "admitted": brief["admitted"], "warnings": brief["warnings"],
                "degraded": judgment.degraded,
                "judgment_hash": sealed["judgment_hash"],
                "input_hash": judgment.input_hash}

    def _tool_outcome(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        record_id = str(args["record_id"])
        judgment_hash = args.get("judgment_hash")
        if not judgment_hash:
            matches = [row for row in read_log(self.log_path)
                       if any(e.get("record_id") == record_id
                              for e in row.get("entries", []))]
            if not matches:
                raise MethodError(
                    -32602, f"no sealed judgment touches {record_id}")
            judgment_hash = matches[-1]["judgment_hash"]
        outcome = append_outcome(
            self.outcomes_path, judgment_hash=str(judgment_hash),
            record_id=record_id, verdict=str(args["verdict"]),
            by=str(args["by"]), note=str(args.get("note", "")))
        return {"outcome": outcome, "chain_length": verify_outcomes(self.outcomes_path)}

    def _tool_calibrate(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        return calibrate(read_log(self.log_path), read_outcomes(self.outcomes_path),
                         action=str(args.get("action", "admit")))

    def _tool_audit(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        if args.get("record_id"):
            return {"record_id": str(args["record_id"]),
                    "judgments": for_record(self.log_path, str(args["record_id"]),
                                            reader=read_log)}
        return summarize(self.log_path, reader=read_log)

    # ---- JSON-RPC ----------------------------------------------------------

    def handle(self, request: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        method = request.get("method")
        msg_id = request.get("id")
        if method == "initialize":
            requested = str(request.get("params", {}).get("protocolVersion", ""))
            version = requested if requested in SUPPORTED_VERSIONS else FALLBACK_VERSION
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"protocolVersion": version,
                               "capabilities": {"tools": {}},
                               "serverInfo": {"name": SERVER_NAME,
                                              "version": SERVER_VERSION}}}
        if msg_id is None:
            return None  # notification (e.g. notifications/initialized)
        try:
            if method == "tools/list":
                result = {"tools": _tool_definitions()}
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    payload = self.call_tool(str(params.get("name")),
                                             params.get("arguments") or {})
                    result = {"content": [{"type": "text",
                                           "text": json.dumps(payload, ensure_ascii=False,
                                                              indent=2)}],
                              "isError": False}
                except (ContractError, ValueError) as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}],
                              "isError": True}
                except Exception as exc:  # noqa: BLE001 - a tool must never
                    # crash the server; the agent sees the failure instead.
                    result = {"content": [{"type": "text",
                                           "text": f"tool failed: {exc}"}],
                              "isError": True}
            elif method == "ping":
                result = {}
            else:
                raise MethodError(-32601, f"method not found: {method}")
        except MethodError as exc:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": exc.code, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev_first.mcp_server",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--dir",
                        default=os.environ.get("JEV_MEMORY_DIR",
                                               str(Path.home() / ".jev-memory")),
                        help="directory for records/judgments/cache/outcomes")
    args = parser.parse_args(argv)
    server = MemoryServer(Path(args.dir).expanduser())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": f"parse error: {exc}"}}
        else:
            if not isinstance(request, dict):
                response = {"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32600, "message": "request must be an object"}}
            else:
                response = server.handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
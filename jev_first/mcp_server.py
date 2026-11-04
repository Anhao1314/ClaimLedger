"""MCP stdio server exposing the Jev-first memory layer.

Zero dependencies: newline-delimited JSON-RPC 2.0 on stdin/stdout, diagnostics
on stderr only. All files live in one directory (--dir, default ~/.jev-memory
or JEV_MEMORY_DIR):

    records.jsonl    append-only, hash-chained records (no stored status)
    judgments.jsonl  sealed judgment log (hash-chained)
    cache.jsonl      judgment cache (derived, deletable)
    outcomes.jsonl   human verdicts (hash-chained)

Tools: memory_propose, memory_decide, memory_brief, memory_calibrate,
memory_audit, memory_proposals. memory_record is a deprecated alias for
memory_propose.

Agent writes are proposals, not records. There is no confirm tool here, and
no outcome tool either: confirmation and outcome review belong to the
console/CLI, so an agent cannot approve its own write or feed its own verdict
into calibration. The proposal log records both sides.

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

from . import proposals as proposal_log
from .audit import for_record, summarize
from .calibration import calibrate
from .cache import Cache
from .contracts import ContractError
from .judge import DEFAULT_BUDGET_BYTES, judge
from .log import append_judgment, read as read_log, verify as verify_log
from .outcomes import read as read_outcomes
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
             "Deprecated alias for memory_propose. Agent writes are proposals, not "
             "records: a human confirms them in the console or CLI. This tool never "
             "appends to the record store."),
         "inputSchema": {"type": "object", "properties": {
             "text": {"type": "string", "description": "one standalone statement"},
             "source": {"type": "string", "description": "who wrote it (agent, tool, human)"},
             "scope": {"type": "string", "description": "optional scope label"}},
             "required": ["text", "source"]}},
        {"name": "memory_propose",
         "description": (
             "Propose ONE decision for human confirmation. The proposal is pending, "
             "not active memory, until a human confirms it outside this server. "
             "Near-duplicates of existing records or pending proposals return the "
             "existing object with created=false."),
         "inputSchema": {"type": "object", "properties": {
             "text": {"type": "string"}, "source": {"type": "string"},
             "scope": {"type": "string"}},
             "required": ["text", "source"]}},
        {"name": "memory_decide",
         "description": (
             "Select candidate records for a task and judge them: one admit choice per "
             "record, pairwise conflict localization, governing, and pairwise edge "
             "classification (proposed graph edges wait for human confirmation). Seals "
             "the judgment and returns its hash; a human records the outcome against "
             "that hash in the console or CLI. Requires TYPESAFE_API_KEY; without "
             "it the result is degraded and every record is review."),
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
        {"name": "memory_proposals",
         "description": ("List pending proposals: agent writes and proposed graph "
                         "edges waiting for a human to confirm or reject them."),
         "inputSchema": {"type": "object", "properties": {}}},
    ]


class MemoryServer:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.store = RecordStore(self.directory / "records.jsonl")
        self.log_path = self.directory / "judgments.jsonl"
        self.cache = Cache(self.directory / "cache.jsonl")
        self.outcomes_path = self.directory / "outcomes.jsonl"
        self.proposals_path = self.directory / "proposals.jsonl"
        self.edges_path = self.directory / "edges.jsonl"

    # ---- tool dispatch -----------------------------------------------------

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        handlers = {
            "memory_record": self._tool_record,
            "memory_propose": self._tool_propose,
            "memory_decide": self._tool_decide,
            "memory_brief": self._tool_brief,
            "memory_calibrate": self._tool_calibrate,
            "memory_audit": self._tool_audit,
            "memory_proposals": self._tool_proposals,
        }
        if name not in handlers:
            raise MethodError(-32602, f"unknown tool: {name}")
        return handlers[name](dict(arguments or {}))

    def _tool_record(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        payload = self._tool_propose(args)
        payload["deprecated"] = ("memory_record is an alias for memory_propose; "
                                 "agent writes require human confirmation")
        return payload

    def _tool_propose(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        text = str(args["text"])
        source = str(args["source"])
        scope = args.get("scope")
        records = self.store.load()
        existing = find_near_duplicate(records, text, scope=scope)
        if existing:
            record, similarity = existing
            return {"created": False, "duplicate": "record",
                    "record": record, "similarity": similarity,
                    "note": "a near-identical record already exists; nothing proposed"}
        pending = proposal_log.pending(self.proposals_path)
        candidates = [{"record_id": p["proposal_id"], "text": p["text"],
                       "scope": p.get("scope")} for p in pending]
        near = find_near_duplicate(candidates, text, scope=scope)
        if near:
            match = next(p for p in pending
                         if p["proposal_id"] == near[0]["record_id"])
            return {"created": False, "duplicate": "pending",
                    "proposal": match, "similarity": near[1]}
        proposal = proposal_log.propose(
            self.proposals_path, text=text, source=source, scope=scope)
        return {"created": True, "status": "pending", "proposal": proposal,
                "note": "awaiting human confirmation; not active memory"}

    def _tool_proposals(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        from . import edges as edge_log
        rows = proposal_log.pending(self.proposals_path)
        pending_edges = edge_log.pending(self.edges_path)
        return {"count": len(rows), "pending": rows,
                "pending_edges": pending_edges,
                "pending_edge_count": len(pending_edges)}

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
        proposed = self._propose_edges(judgment,
                                       judgment_hash=sealed["judgment_hash"])
        brief = render_brief(judgment)
        payload = {
            "brief": brief["text"],
            "admitted": brief["admitted"],
            "warnings": brief["warnings"],
            "conflicts": brief["conflicts"],
            "edges": proposed,
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

    def _propose_edges(self, judgment, *, judgment_hash: str) -> list:
        """Append policy-cleared edge proposals to the log. Idempotent: a
        judgment that re-runs must not duplicate an already-proposed edge."""
        from . import edges as edge_log
        proposed = []
        for decision in judgment.edges:
            if decision.action != "proposed":
                continue
            source = "jev" if decision.via == "single-question" else f"jev:{decision.via}"
            body = edge_log.propose_edge(
                self.edges_path, src=decision.src, dst=decision.dst,
                edge_type=decision.label, confidence=decision.p,
                source=source, judgment_hash=judgment_hash,
                direction=decision.direction)
            if body is not None:
                proposed.append(body)
        return proposed

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

    def _tool_calibrate(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        return calibrate(read_log(self.log_path), read_outcomes(self.outcomes_path),
                         action=str(args.get("action", "admit")))

    def _tool_audit(self, args: Mapping[str, Any]) -> Dict[str, Any]:
        if args.get("record_id"):
            return {"record_id": str(args["record_id"]),
                    "judgments": for_record(self.log_path, str(args["record_id"]),
                                            reader=read_log)}
        summary = summarize(self.log_path, reader=read_log)
        from . import edges as edge_log
        try:
            edge_count = edge_log.verify(self.edges_path)
            edge_statuses = edge_log.statuses(self.edges_path)
            summary["edge_events"] = edge_count
            summary["edge_statuses"] = {
                "pending": sum(1 for s in edge_statuses.values() if s == "pending"),
                "confirmed": sum(1 for s in edge_statuses.values() if s == "confirmed"),
                "rejected": sum(1 for s in edge_statuses.values() if s == "rejected"),
            }
        except ValueError as exc:
            summary["edge_events"] = f"CORRUPT: {exc}"
        return summary

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
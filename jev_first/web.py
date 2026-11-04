"""memory console — a local, single-user view over the Jev-first layer.

This is not a product surface. It exists for one reason: **to collect
outcomes**. A human works through this console, clicks upheld / overturned on
real decisions, and the calibration view finally has data. If it ever drifts
into decoration, cut it again (same rule that removed the old demo).

stdlib only. Binds to 127.0.0.1. Every number on the page comes from a live
engine call or a committed log — nothing hardcoded.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import parse_qs, urlparse

from . import agents as agent_registry
from . import log as jlog
from . import proposals as proposal_log
from .audit import for_record
from .brief import render_brief
from .judge import Judgment
from .cache import Cache
from .calibration import calibrate
from .judge import DEFAULT_BUDGET_BYTES, judge
from .outcomes import append_outcome, read as read_outcomes, verify as verify_outcomes
from .records import RecordStore, find_near_duplicate
from .select import select_candidates

from .web_page import PAGE


class Console:
    """Stateful view over one store + one directory of chain files."""

    def __init__(self, store_path: Path, directory: Path):
        self.store = RecordStore(store_path)
        self.cache = Cache(directory / "cache.jsonl")
        self.log_path = directory / "judgments.jsonl"
        self.outcomes_path = directory / "outcomes.jsonl"
        self.agents_path = directory / "agents.jsonl"
        self.proposals_path = directory / "proposals.jsonl"
        self.edges_path = directory / "edges.jsonl"
        self.last: Optional[Dict[str, Any]] = None

    # ---- endpoints ---------------------------------------------------------

    def api_decide(self, params: Mapping[str, str]) -> Dict[str, Any]:
        task = (params.get("task") or "").strip()
        if not task:
            return {"error": "task is required"}
        records = self.store.load()
        if not records:
            return {"error": "record store is empty — add records first"}
        limit = min(max(int(params.get("limit", 6)), 1), 6)
        candidates, stats = select_candidates(records, task,
                                              scope=params.get("scope"),
                                              limit=limit)
        if not candidates:
            return {"error": "no candidates in scope for this task"}
        budget = int(params.get("budget", DEFAULT_BUDGET_BYTES))
        judgment = judge(task, candidates, budget_bytes=budget,
                         on_error="review", cache=self.cache)
        judgment = replace(judgment, selection=stats)
        brief = render_brief(judgment)
        sealed = jlog.append_judgment(self.log_path, judgment.to_dict())
        outcomes = {o["record_id"]: o["verdict"]
                    for o in read_outcomes(self.outcomes_path)
                    if o.get("judgment_hash") == sealed["judgment_hash"]}
        self.last = sealed
        return {
            "task": task, "model": judgment.model,
            "question_set_version": judgment.question_set_version,
            "policy": judgment.policy, "degraded": judgment.degraded,
            "latency_ms": judgment.latency_ms, "requests": judgment.requests,
            "entries": judgment.to_dict()["entries"],
            "conflicts": judgment.conflicts,
            "uncertain_pairs": judgment.uncertain_pairs,
            "governing": judgment.governing,
            "used_bytes": judgment.used_bytes, "budget_bytes": judgment.budget_bytes,
            "omitted": judgment.omitted, "selection": stats,
            "brief_text": brief["text"], "brief_bytes": brief["bytes"],
            "judgment_hash": sealed["judgment_hash"], "outcomes": outcomes,
        }

    def api_record(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        text = str(body["text"])
        source = str(body.get("source", "console"))
        scope = body.get("scope")
        records = self.store.load()
        existing = find_near_duplicate(records, text, scope=scope)
        if existing:
            record, similarity = existing
            return {"record": record, "created": False, "duplicate": "near",
                    "similarity": similarity, "total_records": len(records)}
        record = self.store.append(text, source, scope=scope)
        return {"record": record, "created": True,
                "total_records": len(records) + 1}

    def api_records(self) -> List[Dict[str, Any]]:
        return self.store.load()

    def api_proposals(self) -> List[Dict[str, Any]]:
        return proposal_log.pending(self.proposals_path)

    def api_edge_proposals(self) -> List[Dict[str, Any]]:
        from . import edges as edge_log
        return edge_log.pending(self.edges_path)

    def api_edge_confirm(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Human decision on a proposed graph edge: confirm or reject."""
        from . import edges as edge_log
        eid = str(body.get("edge_id", ""))
        decision = str(body.get("decision", "confirm"))
        by = str(body.get("by", "console-human"))
        proposal = edge_log.get(self.edges_path, eid)
        if proposal is None:
            return {"error": f"unknown edge proposal: {eid}"}
        if edge_log.decision_for(self.edges_path, eid) is not None:
            return {"error": f"edge already decided: {eid}"}
        if decision in ("reject", "rejected"):
            event = edge_log.decide_edge(self.edges_path, eid,
                                         decision="rejected", by=by)
            return {"decision": event, "created": False}
        if decision not in ("confirm", "confirmed"):
            return {"error": "decision must be confirm or reject"}
        event = edge_log.decide_edge(self.edges_path, eid,
                                     decision="confirmed", by=by)
        return {"decision": event, "created": True}

    def api_confirm(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Human decision on an agent proposal: confirm appends the record."""
        pid = str(body.get("proposal_id", ""))
        decision = str(body.get("decision", "confirm"))
        by = str(body.get("by", "console-human"))
        proposal = proposal_log.get(self.proposals_path, pid)
        if proposal is None:
            return {"error": f"unknown proposal: {pid}"}
        if proposal_log.decision_for(self.proposals_path, pid) is not None:
            return {"error": f"proposal already decided: {pid}"}
        if decision in ("reject", "rejected"):
            event = proposal_log.decide(self.proposals_path, pid,
                                        decision="rejected", by=by)
            return {"decision": event, "record": None, "created": False}
        if decision not in ("confirm", "confirmed"):
            return {"error": "decision must be confirm or reject"}
        existing = find_near_duplicate(self.store.load(), str(proposal["text"]),
                                       scope=proposal.get("scope"))
        if existing:
            record = existing[0]
            created = False
        else:
            record = self.store.append(str(proposal["text"]),
                                       str(proposal["source"]),
                                       scope=proposal.get("scope"))
            created = True
        event = proposal_log.decide(self.proposals_path, pid,
                                    decision="confirmed", by=by,
                                    record_id=record["record_id"])
        return {"decision": event, "record": record, "created": created}

    def api_history(self, limit: int = 40) -> List[Dict[str, Any]]:
        """Recent sealed judgments, newest first, with their recorded outcomes."""
        rows = jlog.read(self.log_path)[-max(1, limit):]
        outcomes = read_outcomes(self.outcomes_path)
        by_hash: Dict[str, Dict[str, str]] = {}
        for outcome in outcomes:
            by_hash.setdefault(outcome.get("judgment_hash"), {})[
                outcome.get("record_id")] = outcome.get("verdict")
        out = []
        for row in reversed(rows):
            try:
                brief_text = render_brief(Judgment.from_dict(row))["text"]
            except (KeyError, TypeError, ValueError):
                brief_text = ""
            out.append({
                "judgment_hash": row.get("judgment_hash"),
                "task": row.get("task", ""),
                "model": row.get("model", "?"),
                "created_at": row.get("created_at", ""),
                "conflicts": row.get("conflicts", []),
                "degraded": row.get("degraded", False),
                "entries": row.get("entries", []),
                "outcomes": by_hash.get(row.get("judgment_hash"), {}),
                "selection": row.get("selection") or {},
                "brief_text": brief_text,
            })
        return out

    def api_agents(self) -> List[Dict[str, Any]]:
        """Registered identities with record counts; unregistered sources still
        appear, flagged, so attribution stays honest."""
        registered = agent_registry.read(self.agents_path)
        counts: Dict[str, int] = {}
        for record in self.store.load():
            source = str(record.get("source", ""))
            counts[source] = counts.get(source, 0) + 1
        out: List[Dict[str, Any]] = []
        for row in registered:
            out.append({**row, "records": counts.get(row["name"], 0),
                        "registered": True})
        known = {row["name"].lower() for row in registered}
        for source, count in sorted(counts.items()):
            if source.lower() not in known:
                out.append({"agent_id": None, "name": source, "kind": "unknown",
                            "created_at": None, "records": count,
                            "registered": False})
        return out

    def api_register_agent(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        entry = agent_registry.append_agent(
            self.agents_path, name=str(body.get("name", "")).strip(),
            kind=str(body.get("kind", "agent")))
        return {"agent": entry,
                "chain_length": agent_registry.verify(self.agents_path)}

    def api_record_history(self, record_id: str) -> List[Dict[str, Any]]:
        return for_record(self.log_path, record_id, reader=jlog.read)

    def api_seed_examples(self) -> Dict[str, Any]:
        """Seed five non-conflicting decisions — only into an empty store.

        The point is the first run: a fresh store cannot produce an `admit`
        verdict, which makes the first interaction feel broken.
        """
        if self.store.load():
            return {"error": "store already has records; seeding is for an empty store"}
        examples = [
            "All storage must use PostgreSQL.",
            "Retries must be capped at 3.",
            "Deployments happen only on Tuesdays.",
            "Logs are retained for 30 days.",
            "API v1 must remain unchanged.",
        ]
        added = [self.store.append(text, "examples") for text in examples]
        try:
            agent_registry.append_agent(self.agents_path, name="examples", kind="agent")
        except ValueError:
            pass
        return {"seeded": len(added),
                "records": [record["record_id"] for record in added]}

    def api_outcome(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        judgment_hash = body.get("judgment_hash") or (
            self.last["judgment_hash"] if self.last else None)
        if not judgment_hash:
            return {"error": "no judgment to attach the outcome to"}
        return {"outcome": append_outcome(
            self.outcomes_path, judgment_hash=str(judgment_hash),
            record_id=str(body["record_id"]), verdict=str(body["verdict"]),
            by=str(body.get("by", "console-human")),
            note=str(body.get("note", "")))}

    def api_calibrate(self) -> Dict[str, Any]:
        return calibrate(jlog.read(self.log_path),
                         read_outcomes(self.outcomes_path), action="admit",
                         records=self.store.load())

    def api_audit(self) -> Dict[str, Any]:
        records = len(self.store.load())
        judgments = jlog.verify(self.log_path)
        outcomes = verify_outcomes(self.outcomes_path)
        from . import edges as edge_log
        edge_statuses = edge_log.statuses(self.edges_path)
        summary = {
            "records": records, "judgments": judgments, "outcomes": outcomes,
            "pending_proposals": len(proposal_log.pending(self.proposals_path)),
            "proposal_events": proposal_log.verify(self.proposals_path),
            "pending_edges": sum(1 for s in edge_statuses.values()
                                 if s == "pending"),
            "confirmed_edges": sum(1 for s in edge_statuses.values()
                                   if s == "confirmed"),
            "edge_events": edge_log.verify(self.edges_path),
            "degraded": sum(1 for r in jlog.read(self.log_path) if r.get("degraded")),
            "confirmed_conflicts": sum(len(r.get("conflicts", []))
                                       for r in jlog.read(self.log_path)),
        }
        return summary


def make_handler(console: Console):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._route_get()
            except Exception as exc:  # noqa: BLE001 - the console must never crash
                self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _route_get(self) -> None:
            route = urlparse(self.path)
            if route.path == "/":
                page = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif route.path == "/api/records":
                self._send(console.api_records())
            elif route.path == "/api/calibrate":
                self._send(console.api_calibrate())
            elif route.path == "/api/audit":
                self._send(console.api_audit())
            elif route.path == "/api/history":
                limit = int(parse_qs(route.query).get("limit", ["40"])[0])
                self._send(console.api_history(limit))
            elif route.path == "/api/agents":
                self._send(console.api_agents())
            elif route.path == "/api/proposals":
                self._send(console.api_proposals())
            elif route.path == "/api/edge-proposals":
                self._send(console.api_edge_proposals())
            elif route.path == "/api/record-history":
                record_id = parse_qs(route.query).get("record_id", [""])[0]
                self._send(console.api_record_history(record_id))
            elif route.path == "/api/decide":
                self._send(console.api_decide(
                    {k: v[0] for k, v in parse_qs(route.query).items()}))
            else:
                self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._route_post()
            except Exception as exc:  # noqa: BLE001
                self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _route_post(self) -> None:
            route = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except json.JSONDecodeError:
                self._send({"error": "body is not JSON"}, 400)
                return
            if route.path == "/api/record":
                self._send(console.api_record(body))
            elif route.path == "/api/agents":
                self._send(console.api_register_agent(body))
            elif route.path == "/api/confirm":
                self._send(console.api_confirm(body))
            elif route.path == "/api/edge-confirm":
                self._send(console.api_edge_confirm(body))
            elif route.path == "/api/seed-examples":
                self._send(console.api_seed_examples())
            elif route.path == "/api/outcome":
                self._send(console.api_outcome(body))
            else:
                self._send({"error": "not found"}, 404)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # keep stdout clean; errors surface in the page

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev_first.console",
                                     description="local memory console (single user)")
    parser.add_argument("--store", required=True, help="records.jsonl path")
    parser.add_argument("--dir", default="~/.jev-memory",
                        help="directory for log/cache/outcomes")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    directory = Path(args.dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    console = Console(Path(args.store).expanduser(), directory)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(console))
    print(f"jev-memory console on http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
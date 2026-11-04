"""Append-only edge log: graph proposals wait for a human, like records do.

The multi-relational memory plane is judged, not written. A judgment that
clears the policy threshold PROPOSES an edge; confirmation is a separate human
event. Both are events in one hash-chained log, so the graph carries its own
audit trail and no edge ever mutates in place.

One chain across proposals and decisions:

    edge proposal(prev=GENESIS)
      decision(prev=proposal.body_hash)

Edge identity is (src, dst, type): re-proposing an existing pending or
confirmed edge is a no-op, not a duplicate. ``supersedes`` always means
src supersedes dst (contracts/edge-schema.v1.json direction convention), so
identity needs no direction field. ``unrelated`` is never proposed — it is the
absence of an edge.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .proposals import body_hash, read  # shared canonical-hash + JSONL readers

GENESIS = "0" * 64
DECISIONS = ("confirmed", "rejected")
EDGE_TYPES = ("supports", "contradicts", "supersedes")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def edge_id(src: str, dst: str, edge_type: str) -> str:
    if edge_type not in EDGE_TYPES:
        raise ValueError(f"edge_type must be one of {EDGE_TYPES}: {edge_type!r}")
    if not isinstance(src, str) or not src or not isinstance(dst, str) or not dst:
        raise ValueError("src and dst must be non-empty strings")
    if src == dst:
        raise ValueError("src and dst must differ")
    return "edg_" + hashlib.sha256(
        f"{src}|{dst}|{edge_type}".encode("utf-8")).hexdigest()[:24]


def statuses(path: os.PathLike | str) -> Dict[str, str]:
    """Current status per edge_id: pending, confirmed, or rejected."""
    out: Dict[str, str] = {}
    for row in read(path):
        if row.get("type") == "proposal":
            out[row["edge_id"]] = "pending"
        elif row.get("type") == "decision":
            out[row["edge_id"]] = row["decision"]
    return out


def pending(path: os.PathLike | str) -> List[Dict[str, Any]]:
    """Undecided edge proposals, newest first."""
    decided = {row["edge_id"] for row in read(path)
               if row.get("type") == "decision"}
    rows = [row for row in read(path)
            if row.get("type") == "proposal" and row["edge_id"] not in decided]
    rows.sort(key=lambda row: str(row.get("at")), reverse=True)
    return rows


def confirmed(path: os.PathLike | str) -> List[Dict[str, Any]]:
    """Confirmed proposals, newest first. The graph's trusted edge set."""
    decided = {}
    for row in read(path):
        if row.get("type") == "decision" and row["decision"] == "confirmed":
            decided[row["edge_id"]] = row
    rows = [row for row in read(path)
            if row.get("type") == "proposal" and row["edge_id"] in decided]
    rows.sort(key=lambda row: str(row.get("at")), reverse=True)
    return rows


def get(path: os.PathLike | str, eid: str) -> Optional[Dict[str, Any]]:
    for row in read(path):
        if row.get("type") == "proposal" and row.get("edge_id") == eid:
            return row
    return None


def decision_for(path: os.PathLike | str, eid: str) -> Optional[Dict[str, Any]]:
    for row in read(path):
        if row.get("type") == "decision" and row.get("edge_id") == eid:
            return row
    return None


def propose_edge(path: os.PathLike | str, *, src: str, dst: str,
                 edge_type: str, confidence: float, source: str,
                 judgment_hash: Optional[str] = None,
                 at: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Append an edge proposal. Returns None when the edge already exists as
    pending or confirmed — proposing a known edge is a no-op, not an error,
    because judgments re-run and must stay idempotent."""
    if not isinstance(src, str) or not src or not isinstance(dst, str) or not dst:
        raise ValueError("src and dst must be non-empty strings")
    if src == dst:
        raise ValueError("src and dst must differ")
    if edge_type not in EDGE_TYPES:
        raise ValueError(f"edge_type must be one of {EDGE_TYPES}: {edge_type!r}")
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be within [0, 1]")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    eid = edge_id(src, dst, edge_type)
    existing = statuses(path).get(eid)
    if existing in ("pending", "confirmed"):
        return None
    rows = read(path)
    body = {
        "type": "proposal", "edge_id": eid, "src": src, "dst": dst,
        "edge_type": edge_type, "confidence": round(float(confidence), 4),
        "source": source, "at": at or _now(),
        "prev_hash": rows[-1]["body_hash"] if rows else GENESIS,
    }
    if judgment_hash:
        body["judgment_hash"] = judgment_hash
    body["body_hash"] = body_hash(body)
    _append(path, body)
    return body


def decide_edge(path: os.PathLike | str, eid: str, *, decision: str, by: str,
                at: Optional[str] = None) -> Dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not isinstance(by, str) or not by.strip():
        raise ValueError("by must be a non-empty string")
    rows = read(path)
    if not any(row.get("type") == "proposal" and row.get("edge_id") == eid
               for row in rows):
        raise ValueError(f"unknown edge proposal: {eid}")
    if any(row.get("type") == "decision" and row.get("edge_id") == eid
           for row in rows):
        raise ValueError(f"edge already decided: {eid}")
    body = {
        "type": "decision", "edge_id": eid, "decision": decision,
        "by": by, "at": at or _now(), "prev_hash": rows[-1]["body_hash"],
    }
    body["body_hash"] = body_hash(body)
    _append(path, body)
    return body


def verify(path: os.PathLike | str) -> int:
    """Recompute the chain; raise on any tampering or ordering violation.

    An edge may be proposed, decided, and proposed again (a rejected edge can
    be re-proposed by a later judgment); what can never happen is two live
    proposals for the same edge, or a decision without a pending proposal."""
    expected_prev = GENESIS
    state: Dict[str, str] = {}
    count = 0
    for row in read(path):
        body = {k: v for k, v in row.items() if k != "body_hash"}
        if body_hash(body) != row.get("body_hash"):
            raise ValueError(f"{path}: body_hash mismatch at event {count + 1}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"{path}: broken chain at event {count + 1}")
        kind = row.get("type")
        eid = row.get("edge_id")
        if kind == "proposal":
            if not eid:
                raise ValueError(f"{path}: missing edge_id at event {count + 1}")
            if state.get(eid) in ("pending", "confirmed"):
                raise ValueError(
                    f"{path}: duplicate edge proposal at event {count + 1}")
            if row.get("edge_type") not in EDGE_TYPES:
                raise ValueError(f"{path}: unknown edge_type at event {count + 1}")
            state[eid] = "pending"
        elif kind == "decision":
            if state.get(eid) != "pending":
                raise ValueError(
                    f"{path}: decision before proposal at event {count + 1}")
            if row.get("decision") not in DECISIONS:
                raise ValueError(f"{path}: unknown decision at event {count + 1}")
            state[eid] = row["decision"]
        else:
            raise ValueError(f"{path}: unknown event type at event {count + 1}")
        expected_prev = row["body_hash"]
        count += 1
    return count


def _append(path: os.PathLike | str, body: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

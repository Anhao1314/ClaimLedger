"""Append-only proposal log: agent writes wait for a human.

A proposal is not a record. Confirmation appends the actual record; rejection
leaves the record store untouched. Both are events in this hash-chained log,
so "who proposed what, and who decided it" stays auditable without putting a
status field on records.

The log has one chain across proposals and decisions:

    proposal(prev=GENESIS)
      decision(prev=proposal.body_hash)

A proposal can be decided once. Decisions must reference an earlier proposal.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

GENESIS = "0" * 64
DECISIONS = ("confirmed", "rejected")


def body_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def proposal_id(text: str, source: str, scope: Optional[str], at: str) -> str:
    return "prp_" + hashlib.sha256(
        f"{text}|{source}|{scope}|{at}".encode("utf-8")).hexdigest()[:12]


def read(path: os.PathLike | str) -> List[Dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(target, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{target}:{lineno}: not JSON") from exc
    return rows


def verify(path: os.PathLike | str) -> int:
    expected_prev = GENESIS
    proposals = set()
    decided = set()
    count = 0
    for row in read(path):
        body = {k: v for k, v in row.items() if k != "body_hash"}
        if body_hash(body) != row.get("body_hash"):
            raise ValueError(f"{path}: body_hash mismatch at event {count + 1}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"{path}: broken chain at event {count + 1}")
        kind = row.get("type")
        if kind == "proposal":
            pid = row.get("proposal_id")
            if not pid or pid in proposals:
                raise ValueError(f"{path}: duplicate proposal at event {count + 1}")
            proposals.add(pid)
        elif kind == "decision":
            pid = row.get("proposal_id")
            if pid not in proposals:
                raise ValueError(f"{path}: decision before proposal at event {count + 1}")
            if pid in decided:
                raise ValueError(f"{path}: proposal decided twice at event {count + 1}")
            if row.get("decision") not in DECISIONS:
                raise ValueError(f"{path}: unknown decision at event {count + 1}")
            decided.add(pid)
        else:
            raise ValueError(f"{path}: unknown event type at event {count + 1}")
        expected_prev = row["body_hash"]
        count += 1
    return count


def statuses(path: os.PathLike | str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in read(path):
        if row.get("type") == "proposal":
            out[row["proposal_id"]] = "pending"
        elif row.get("type") == "decision":
            out[row["proposal_id"]] = row["decision"]
    return out


def pending(path: os.PathLike | str) -> List[Dict[str, Any]]:
    """Undecided proposals, newest first."""
    decided = {row["proposal_id"] for row in read(path)
               if row.get("type") == "decision"}
    rows = [row for row in read(path)
            if row.get("type") == "proposal"
            and row["proposal_id"] not in decided]
    rows.sort(key=lambda row: str(row.get("at")), reverse=True)
    return rows


def get(path: os.PathLike | str, pid: str) -> Optional[Dict[str, Any]]:
    for row in read(path):
        if row.get("type") == "proposal" and row.get("proposal_id") == pid:
            return row
    return None


def decision_for(path: os.PathLike | str, pid: str) -> Optional[Dict[str, Any]]:
    for row in read(path):
        if row.get("type") == "decision" and row.get("proposal_id") == pid:
            return row
    return None


def propose(path: os.PathLike | str, *, text: str, source: str,
            scope: Optional[str] = None, at: Optional[str] = None
            ) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    at = at or _now()
    rows = read(path)
    pid = proposal_id(text, source, scope, at)
    if any(row.get("type") == "proposal" and row.get("proposal_id") == pid
           for row in rows):
        raise ValueError(f"proposal already exists: {pid}")
    body = {
        "type": "proposal", "proposal_id": pid, "text": text,
        "source": source, "scope": scope, "at": at,
        "prev_hash": rows[-1]["body_hash"] if rows else GENESIS,
    }
    body["body_hash"] = body_hash(body)
    _append(path, body)
    return body


def decide(path: os.PathLike | str, pid: str, *, decision: str, by: str,
           at: Optional[str] = None, record_id: Optional[str] = None
           ) -> Dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not isinstance(by, str) or not by.strip():
        raise ValueError("by must be a non-empty string")
    if decision == "confirmed" and not record_id:
        raise ValueError("confirmed requires the record_id it created")
    if decision == "rejected" and record_id:
        raise ValueError("rejected must not carry a record_id")
    rows = read(path)
    if not any(row.get("type") == "proposal" and row.get("proposal_id") == pid
               for row in rows):
        raise ValueError(f"unknown proposal: {pid}")
    if any(row.get("type") == "decision" and row.get("proposal_id") == pid
           for row in rows):
        raise ValueError(f"proposal already decided: {pid}")
    body = {
        "type": "decision", "proposal_id": pid, "decision": decision,
        "by": by, "at": at or _now(), "prev_hash": rows[-1]["body_hash"],
    }
    if record_id:
        body["record_id"] = record_id
    body["body_hash"] = body_hash(body)
    _append(path, body)
    return body


def _append(path: os.PathLike | str, body: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
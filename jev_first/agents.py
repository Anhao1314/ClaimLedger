"""Append-only agent registry.

**What registration means here: attribution, not authentication.** A registry
entry records who claims authorship of records. It carries no keys and no
signatures, so it cannot prove that an agent is who it says — an impostor can
register the same name only if the name is free, and cannot forge an existing
one's past records because records are append-only and hash-chained.

What it does NOT do, by design:

* it does not gate writes — an unregistered ``source`` is still accepted
  (fail-open; existing stores already contain ``agent`` / ``human`` / ``console``)
* it does not create trust scores — per-agent calibration is a later step
* it does not stop an agent from lying about its name

Cryptographic identity (keypairs, signed records) belongs to the relay/merge
phase and is deliberately absent here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

GENESIS = "0" * 64
KINDS = ("agent", "human")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def body_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_agent(path: os.PathLike | str, *, name: str, kind: str = "agent",
                 at: Optional[str] = None) -> Dict[str, Any]:
    """Register one identity. Names are unique; exact repeats are refused."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("name must be 1-64 chars of [A-Za-z0-9._-]")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    rows = read(path)
    if any(row["name"].lower() == name.lower() for row in rows):
        raise ValueError(f"agent name already registered: {name}")
    if at is None:
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "agent_id": "agt_" + hashlib.sha256(
            f"{name}|{kind}|{at}".encode("utf-8")).hexdigest()[:12],
        "name": name, "kind": kind, "created_at": at,
        "prev_hash": rows[-1]["agent_hash"] if rows else GENESIS,
    }
    body["agent_hash"] = body_hash(body)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return body


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
    expected_prev: str = GENESIS
    count = 0
    for row in read(path):
        body = {k: v for k, v in row.items() if k != "agent_hash"}
        if body_hash(body) != row.get("agent_hash"):
            raise ValueError(f"{path}: agent_hash mismatch at entry {count + 1}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"{path}: broken chain at entry {count + 1}")
        expected_prev = row["agent_hash"]
        count += 1
    return count


def resolve(path: os.PathLike | str, name: str) -> Optional[Dict[str, Any]]:
    for row in read(path):
        if row["name"].lower() == str(name).lower():
            return row
    return None
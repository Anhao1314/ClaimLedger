"""Append-only judgment log with a hash chain.

Every line is one sealed judgment: ``prev_hash`` points at the previous
judgment's ``judgment_hash``, and ``judgment_hash`` is sha256 over the judgment
body without the hash fields. Verifying the file re-derives both.

The cache answers "have I seen this input"; the log answers "what did the
system actually decide, in what order, and has anyone touched it since".
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .records import GENESIS, body_hash

_STRIP = ("judgment_hash", "prev_hash", "cached")


def append_judgment(path: os.PathLike | str, body: Mapping[str, Any]) -> Dict[str, Any]:
    """Seal one judgment onto the chain and write it. Returns the sealed body."""
    clean = {k: v for k, v in dict(body).items() if k not in _STRIP}
    rows = read(path)
    clean["prev_hash"] = rows[-1]["judgment_hash"] if rows else GENESIS
    clean["judgment_hash"] = body_hash(clean)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(clean, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return clean


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
    """Re-derive every hash and the chain. Raises on any mismatch."""
    expected_prev: str = GENESIS
    count = 0
    for row in read(path):
        body = {k: v for k, v in row.items() if k != "judgment_hash"}
        if body_hash(body) != row.get("judgment_hash"):
            raise ValueError(f"{path}: judgment_hash mismatch at entry {count + 1}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"{path}: broken chain at entry {count + 1}")
        expected_prev = row["judgment_hash"]
        count += 1
    return count
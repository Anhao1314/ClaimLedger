"""Append-only outcome log: how past judgments turned out.

An outcome is a human (or authorized agent) saying, after the fact, whether a
sealed judgment's action for a record was right. Outcomes are the only input
the calibration view trusts — the system never grades its own judgments.

Hash-chained like everything else. Verdicts are a closed set; "unclear" is a
first-class answer, not a failure.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

GENESIS = "0" * 64
VERDICTS = ("upheld", "overturned", "unclear")


def body_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_outcome(path: os.PathLike | str, *, judgment_hash: str,
                   record_id: str, verdict: str, by: str,
                   note: str = "", at: Optional[str] = None) -> Dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if at is None:
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = read(path)
    body = {
        "judgment_hash": judgment_hash, "record_id": record_id,
        "verdict": verdict, "by": by, "note": note, "at": at,
        "prev_hash": rows[-1]["outcome_hash"] if rows else GENESIS,
    }
    body["outcome_hash"] = body_hash(body)
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
        body = {k: v for k, v in row.items() if k != "outcome_hash"}
        if row.get("verdict") not in VERDICTS:
            raise ValueError(f"{path}: invalid verdict at entry {count + 1}")
        if body_hash(body) != row.get("outcome_hash"):
            raise ValueError(f"{path}: outcome_hash mismatch at entry {count + 1}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"{path}: broken chain at entry {count + 1}")
        expected_prev = row["outcome_hash"]
        count += 1
    return count
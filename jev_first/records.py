"""Append-only record store per contracts/records.v1.json.

Records carry text, source, time, scope and a hash chain — and nothing else.
Whether a record still holds is a judgment, never a stored field.

Chain semantics: ``record[N].prev_hash = body_hash(record[N-1])``, where
``body_hash`` is sha256 over the record's own canonical JSON (which already
contains its own ``prev_hash``). Genesis is 64 zeros.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import ContractError, make_record, validate_record

GENESIS = "0" * 64


def body_hash(record: Dict[str, Any]) -> str:
    """sha256 over the record's canonical JSON, all fields included."""
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordStore:
    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)

    def append(self, text: str, source: str, *, at: Optional[str] = None,
               scope: Optional[str] = None) -> Dict[str, Any]:
        if at is None:
            at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = make_record(text, source, at, scope=scope,
                             prev_hash=self.last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def load(self) -> List[Dict[str, Any]]:
        """Load and verify the whole chain. Raises on any tampering."""
        if not self.path.exists():
            return []
        records: List[Dict[str, Any]] = []
        expected_prev: str = GENESIS
        with open(self.path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ContractError(f"{self.path}:{lineno}: not JSON") from exc
                try:
                    validate_record(record)
                except ContractError as exc:
                    raise ContractError(f"{self.path}:{lineno}: {exc}") from None
                if record["prev_hash"] != expected_prev:
                    raise ContractError(f"{self.path}:{lineno}: broken hash chain")
                if any(r["record_id"] == record["record_id"] for r in records):
                    raise ContractError(f"{self.path}:{lineno}: duplicate record_id")
                records.append(record)
                expected_prev = body_hash(record)
        return records

    def last_hash(self) -> str:
        records = self.load()
        return body_hash(records[-1]) if records else GENESIS
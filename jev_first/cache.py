"""Judgment cache.

Keyed by ``input_hash`` — a hash over the task, the exact record set, the exact
question payloads, the model, and the question-set version. Anything that could
change the answer changes the key.

One JSON object per line; lookup is a scan, which is fine at this scale. The
cache is derived data: deleting it costs latency, never correctness.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def input_hash(task: str, records: list, questions: Dict[str, Any], *,
               model: str, question_set_version: str) -> str:
    body = {"task": task, "records": list(records), "questions": questions,
            "model": model, "question_set_version": question_set_version}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("input_hash") == key:
                    return record
        return None

    def put(self, key: str, body: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({**body, "input_hash": key},
                                    ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
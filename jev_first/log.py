"""Append-only decision log.

This file is the artifact that makes "change models, keep memory" checkable:
the same question set, the same policy, and a probability distribution recorded
per decision. Swap the generation model, replay, compare.

One JSON object per line. No rewriting, no compaction.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

from .decide import Decision

PathLike = Union[str, os.PathLike]


def append(path: PathLike, decision: Decision, *, extra: Mapping[str, Any] = None) -> Dict[str, Any]:
    """Append one decision and return the record that was written."""
    record = decision.to_dict()
    if extra:
        record = {**record, **dict(extra)}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def read(path: PathLike) -> List[Dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(target, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{target}:{lineno}: not JSON") from exc
    return out
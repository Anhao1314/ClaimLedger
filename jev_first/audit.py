"""audit view: what did the system decide, when, and has anyone touched it."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


def summarize(path: str, *, reader) -> Dict[str, Any]:
    """Read a sealed judgment log via ``reader`` and summarize it.

    ``reader`` is ``jev_first.log.read`` in production; tests inject fakes.
    Chain verification is the caller's job (``log.verify``) — this view
    summarizes, it does not re-verify.
    """
    rows = reader(path)
    models: Dict[str, int] = {}
    degraded = 0
    conflicts = 0
    uncertain = 0
    for row in rows:
        models[row.get("model", "?")] = models.get(row.get("model", "?"), 0) + 1
        if row.get("degraded"):
            degraded += 1
        conflicts += len(row.get("conflicts", []))
        uncertain += len(row.get("uncertain_pairs", []))
    times = sorted(row["created_at"] for row in rows if row.get("created_at"))
    return {
        "n_judgments": len(rows),
        "models": models,
        "degraded": degraded,
        "confirmed_conflicts": conflicts,
        "uncertain_pairs": uncertain,
        "first": times[0] if times else None,
        "last": times[-1] if times else None,
    }


def for_record(path: str, record_id: str, *, reader) -> List[Dict[str, Any]]:
    """Every sealed judgment in which this record took part, newest first."""
    out = []
    for row in reader(path):
        touched = any(e.get("record_id") == record_id
                      for e in row.get("entries", []))
        if touched:
            entry = next(e for e in row["entries"]
                         if e.get("record_id") == record_id)
            out.append({
                "judgment_hash": row.get("judgment_hash"),
                "task": row.get("task"),
                "created_at": row.get("created_at"),
                "action": entry.get("action"),
                "p_admit": entry.get("p_admit"),
                "governing": entry.get("governing"),
                "conflicted": entry.get("conflicted"),
                "low_margin": entry.get("low_margin"),
                "degraded": row.get("degraded", False),
            })
    return sorted(out, key=lambda item: str(item.get("created_at")), reverse=True)


def timeline(path: str, *, reader, limit: int = 20) -> List[Dict[str, Any]]:
    """The decision history, newest first, one line per judgment."""
    rows = list(reader(path))
    rows.reverse()
    out = []
    for row in rows[:limit]:
        out.append({
            "judgment_hash": row.get("judgment_hash"),
            "task": row.get("task"),
            "model": row.get("model"),
            "created_at": row.get("created_at"),
            "actions": {e["record_id"]: e["action"]
                        for e in row.get("entries", [])},
            "conflicts": row.get("conflicts", []),
            "degraded": row.get("degraded", False),
        })
    return out
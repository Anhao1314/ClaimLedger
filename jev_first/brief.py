"""brief: the deterministic text projection an agent actually reads.

Everything in it is derived from one sealed judgment — the admitted records,
the unresolved conflicts, the thin margins. Same judgment in, same brief out.

Only records whose action is `admit` appear as active constraints. A record
under review — conflicted, thin margin, or the model's own hedge — must never
read as something the agent may rely on.

When selection fell back to recency because nothing matched lexically, the
brief says so: an agent should see "no relevant records", not a weak candidate
dressed up as a human-review item.
"""
from __future__ import annotations

from typing import Any, Dict, List

ADMIT = "admit"
REVIEW = "review"


def render_brief(judgment: Any) -> Dict[str, Any]:
    """Project a Judgment into the block an agent sees. Never calls a model."""
    lines: List[str] = [f"TASK: {judgment.task}", ""]
    warnings: List[str] = []

    fallback = bool(getattr(judgment, "selection", {}).get("fallback_to_recency"))

    admitted = sorted((e for e in judgment.entries
                       if e.action == ADMIT and e.included),
                      key=lambda e: (e.p_admit or 0.0), reverse=True)
    review = sorted((e for e in judgment.entries
                     if e.action == REVIEW and e.included),
                    key=lambda e: (e.p_admit or 0.0), reverse=True)
    conflicts = judgment.conflicts or []
    texts = {e.record_id: e.text for e in judgment.entries}

    if fallback and not admitted:
        lines.append("NO RELEVANT RECORDS: nothing in memory matches this task "
                     "lexically. The candidates below were selected by recency, "
                     "not relevance, and none were admitted.")

    if admitted:
        lines.append("ACTIVE CONSTRAINTS (must follow):")
        for entry in admitted:
            marker = ""
            if entry.governing:
                marker = " [governing]"
            elif entry.low_margin:
                marker = " [thin margin — confirm before relying]"
            lines.append(f"- {entry.text}{marker}")
        if fallback:
            lines.append("")
            lines.append("NOTE: no lexical match — the judge admitted the record(s) "
                         "above semantically; confirm before relying.")
    elif not fallback:
        lines.append("ACTIVE CONSTRAINTS: none admitted for this task.")

    if review:
        lines.append("")
        if fallback:
            lines.append("CANDIDATES CONSIDERED (recency fallback — not admitted):")
        else:
            lines.append("NEEDS HUMAN REVIEW (not admitted — do not rely yet):")
        for entry in review:
            if entry.conflicted:
                reason = "conflicts with another record"
            elif entry.low_margin:
                reason = "thin margin"
            else:
                reason = "model asked for review"
            lines.append(f"- {texts.get(entry.record_id, entry.record_id)} "
                         f"[{reason}]")
        warnings.extend(e.record_id for e in review)

    if conflicts:
        lines.append("")
        lines.append("UNRESOLVED CONFLICTS (resolve with a human before acting):")
        for pair in conflicts:
            lines.append(f"- {texts.get(pair[0], pair[0])}  ⟂  "
                         f"{texts.get(pair[1], pair[1])}")

    if judgment.degraded:
        lines.append("")
        lines.append("NOTE: judgment ran degraded (transport failure) — every "
                     "record is review; do not act without human confirmation.")
        warnings.append("degraded")

    text = "\n".join(lines)
    return {
        "text": text,
        "bytes": len(text.encode("utf-8")),
        "admitted": len(admitted),
        "warnings": warnings,
        "conflicts": [list(pair) for pair in (conflicts or [])],
        "input_hash": judgment.input_hash,
        "fallback_to_recency": fallback,
    }
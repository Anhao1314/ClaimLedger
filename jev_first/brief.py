"""brief: the deterministic text projection an agent actually reads.

Everything in it is derived from one sealed judgment — the admitted records,
the unresolved conflicts, the thin margins. Same judgment in, same brief out.

Only records whose action is `admit` appear as active constraints. A record
under review — conflicted, thin margin, or the model's own hedge — must never
read as something the agent may rely on.

When selection fell back to recency because nothing matched lexically, the
brief says so: an agent should see "no relevant records", not a weak candidate
dressed up as a human-review item.

Confirmed graph edges (human-confirmed in the edge log) are overlaid when the
caller supplies them. They never invent content: they annotate records that
are already in the brief and surface conflict knowledge learned on earlier
tasks. A confirmed `supersedes` edge is the strongest signal in the system —
a retired constraint must not read as something to follow.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ADMIT = "admit"
REVIEW = "review"

_TEXT_PREVIEW = 60


def _preview(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= _TEXT_PREVIEW else text[: _TEXT_PREVIEW - 1] + "…"


def _graph_overlay(judgment: Any, confirmed_edges: List[Dict[str, Any]]
                   ) -> Dict[str, Any]:
    """Project confirmed edges onto the records visible in this judgment.

    Returns line annotations for admitted records plus a known-conflicts list
    for graph conflicts not already surfaced by this run's relation stage.
    Deterministic: same edges in, same overlay out."""
    texts = {e.record_id: e.text for e in judgment.entries}
    present = set(texts)
    superseded: Dict[str, str] = {}   # record_id -> annotation
    supported: Dict[str, List[str]] = {}  # record_id -> [other previews]
    known_conflicts: List[List[str]] = []
    run_conflicts = {frozenset(pair) for pair in (judgment.conflicts or [])}

    for edge in sorted(confirmed_edges,
                       key=lambda e: (e.get("edge_type", ""),
                                      e.get("edge_id", ""))):
        etype = edge.get("edge_type")
        src, dst = edge.get("src"), edge.get("dst")
        if etype == "supersedes":
            newer, older = ((src, dst)
                            if edge.get("direction", "src→dst") == "src→dst"
                            else (dst, src))
            # Only a must-follow record that is actually retired needs the
            # warning; a review-band record already carries its reason.
            if older in present:
                newer_text = texts.get(newer)
                label = (_preview(newer_text) if newer_text
                         else str(newer)[:14])
                superseded[older] = f"superseded by {label}"
        elif etype == "contradicts":
            if src in present and dst in present \
                    and frozenset((src, dst)) not in run_conflicts:
                known_conflicts.append([src, dst])
        elif etype == "supports":
            if src in present and dst in present:
                for a, b in ((src, dst), (dst, src)):
                    other_text = texts.get(b)
                    related = _preview(other_text) if other_text else str(b)[:14]
                    supported.setdefault(a, []).append(related)

    for key in supported:
        supported[key] = sorted(dict.fromkeys(supported[key]))
    known_conflicts.sort()
    return {"superseded": superseded, "supported": supported,
            "known_conflicts": known_conflicts}


def render_brief(judgment: Any, *,
                 confirmed_edges: Optional[List[Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    """Project a Judgment into the block an agent sees. Never calls a model."""
    lines: List[str] = [f"TASK: {judgment.task}", ""]
    warnings: List[str] = []

    fallback = bool(getattr(judgment, "selection", {}).get("fallback_to_recency"))
    overlay = (_graph_overlay(judgment, confirmed_edges)
               if confirmed_edges else
               {"superseded": {}, "supported": {}, "known_conflicts": []})

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
            markers = []
            if entry.governing:
                markers.append("governing")
            elif entry.low_margin:
                markers.append("thin margin — confirm before relying")
            if entry.record_id in overlay["superseded"]:
                markers.append(overlay["superseded"][entry.record_id]
                               + " — confirm before relying")
            elif entry.record_id in overlay["supported"]:
                markers.append("supported by: "
                               + "; ".join(overlay["supported"][entry.record_id]))
            marker = f" [{markers[0]}]" if len(markers) == 1 else \
                (" [" + "; ".join(markers) + "]" if markers else "")
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
            if entry.record_id in overlay["superseded"]:
                reason += "; " + overlay["superseded"][entry.record_id]
            lines.append(f"- {texts.get(entry.record_id, entry.record_id)} "
                         f"[{reason}]")
        warnings.extend(e.record_id for e in review)

    if conflicts:
        lines.append("")
        lines.append("UNRESOLVED CONFLICTS (resolve with a human before acting):")
        for pair in conflicts:
            lines.append(f"- {texts.get(pair[0], pair[0])}  ⟂  "
                         f"{texts.get(pair[1], pair[1])}")

    graph_conflicts = overlay["known_conflicts"]
    if graph_conflicts:
        lines.append("")
        lines.append("KNOWN CONFLICTS (confirmed in the graph on earlier tasks):")
        for pair in graph_conflicts:
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
        "graph_conflicts": [list(pair) for pair in graph_conflicts],
        "input_hash": judgment.input_hash,
        "fallback_to_recency": fallback,
    }

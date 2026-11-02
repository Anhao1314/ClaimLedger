"""Candidate selection: the entrance optimizes recall, not precision.

Design constraints, in order:

1. Records carry no validity status, so the entrance *cannot* filter by
   "still holds" — and must not try. Both sides of a conflict have to reach
   the judge, or stage 2 has nothing to adjudicate.
2. Precision belongs to the judgment layer (`admit` choice + pairwise
   relation). A dumb entrance that occasionally pulls irrelevant records is
   fine: stage 1 excludes them. A smart entrance that silently drops a
   relevant one is fatal: stage 2 never sees the conflict.
3. Cheap and deterministic: scope match, then bag-of-words overlap against
   the task, recency as tie-breaker and as the zero-hit fallback.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

TOKEN = re.compile(r"\w+", re.UNICODE)

# Small on purpose. Domain words like "use", "storage", "deploy" carry signal.
STOPWORDS = frozenset(
    "the a an for to of in on and or is are be at by from as that this it its "
    "with was were will would should".split())


def tokens(text: str) -> set:
    return {t for t in TOKEN.findall(text.lower())
            if t not in STOPWORDS and len(t) > 1}


def select_candidates(records: Sequence[Mapping[str, Any]], task: str, *,
                      scope: Optional[str] = None,
                      limit: int = 6) -> tuple:
    """Pick the records a task should be judged against.

    Returns ``(candidates, stats)``. ``stats`` is part of the audit trail:
    how many records were in scope, how many matched lexically, whether the
    recency fallback fired, and how many were left out.
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    task_tokens = tokens(task)
    in_scope = [r for r in records
                if scope is None or r.get("scope") in (None, scope)]

    scored = [(len(task_tokens & tokens(str(r["text"]))), r) for r in in_scope]
    hits = [item for item in scored if item[0] > 0]
    fallback = not hits
    if fallback:
        # Recall bias: with no lexical signal, recent records are the best
        # guess. Stage 1 excludes whatever is irrelevant.
        ranked = sorted(in_scope, key=lambda r: str(r["at"]), reverse=True)
    else:
        # overlap desc, then most recent first
        ranked = [r for _, r in sorted(
            hits, key=lambda item: (item[0], str(item[1]["at"])),
            reverse=True)]
    selected = ranked[:limit]
    stats = {
        "total_records": len(records),
        "in_scope": len(in_scope),
        "lexical_hits": len(hits),
        "fallback_to_recency": fallback,
        "selected": len(selected),
        "omitted": len(in_scope) - len(selected),
        "limit": limit,
    }
    return selected, stats
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

def select_hybrid(records: Sequence[Mapping[str, Any]], task: str, *,
                  embedder: Optional[Any] = None,
                  scope: Optional[str] = None,
                  limit: int = 6) -> tuple:
    """Lexical candidates ∪ dense-vector candidates — the recall entry.

    The judgment layer still owns precision; the embedding channel only widens
    recall, following the same bias as the lexical path (a missed record is
    fatal, an irrelevant one is cheap). ``embedder`` is any callable mapping a
    list of texts to a sequence of float vectors (L2-normalized recommended;
    cosine is computed defensively). With no embedder — or when it raises —
    this degrades to exactly ``select_candidates`` (fail open).

    Stats gain ``embedding_hits`` (records with positive cosine),
    ``embedding_added`` (how many the union actually gained) and
    ``embedding_error`` (set when the embedder failed and the path degraded).
    """
    lexical, stats = select_candidates(records, task, scope=scope, limit=limit)
    stats = dict(stats, embedding_hits=0, embedding_added=0,
                 embedding_error=None)
    if embedder is None:
        return lexical, stats

    in_scope = [r for r in records
                if scope is None or r.get("scope") in (None, scope)]
    if not in_scope:
        return lexical, stats
    try:
        rec_vecs = list(embedder([str(r["text"]) for r in in_scope]))
        task_vec = list(embedder([task])[0])
    except Exception as exc:  # noqa: BLE001 - recall must never die on an embedder
        stats["embedding_error"] = f"{type(exc).__name__}: {exc}"[:120]
        return lexical, stats

    def cosine(a: Sequence[float], b: Sequence[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    sims = sorted(((cosine(v, task_vec), r) for v, r in zip(rec_vecs, in_scope)),
                  key=lambda item: item[0], reverse=True)
    stats["embedding_hits"] = sum(1 for sim, _ in sims if sim > 0)
    chosen = list(lexical)
    chosen_ids = {str(r.get("record_id")) for r in chosen}
    for _sim, record in sims:
        if len(chosen) >= limit:
            break
        rid = str(record.get("record_id"))
        if rid in chosen_ids:
            continue
        chosen.append(record)
        chosen_ids.add(rid)
        stats["embedding_added"] += 1
    stats["selected"] = len(chosen)
    return chosen, stats

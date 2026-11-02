"""One decision = one request = one typed, auditable result."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from chat_distiller import jev

from .policy import ADMIT, EXCLUDE, Policy
from .questions import build_questions, render_state

Caller = Callable[[str, Mapping[str, Mapping[str, Any]]], Mapping[str, Any]]
DEFAULT_BUDGET_BYTES = 2048


@dataclass(frozen=True)
class Entry:
    claim_id: str
    text: str
    p_applies: float
    p_holds: float
    score: float
    action: str
    included: bool
    governing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "p_applies": round(self.p_applies, 4),
            "p_holds": round(self.p_holds, 4),
            "score": round(self.score, 4),
            "action": self.action,
            "included": self.included,
            "governing": self.governing,
        }


@dataclass(frozen=True)
class Decision:
    task: str
    model: str
    policy: Dict[str, Any]
    entries: Sequence[Entry]
    contradiction: float
    governing: Optional[str]
    governing_confidence: Optional[float]
    used_bytes: int
    budget_bytes: int
    omitted: int
    latency_ms: int
    usage: Dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> List[Entry]:
        return [e for e in self.entries if e.included]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "model": self.model,
            "policy": self.policy,
            "contradiction": round(self.contradiction, 4),
            "governing": self.governing,
            "governing_confidence": (
                round(self.governing_confidence, 4)
                if self.governing_confidence is not None else None
            ),
            "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes,
            "omitted": self.omitted,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "entries": [e.to_dict() for e in self.entries],
        }


def _prob(answer: Mapping[str, Any], key: str, question_id: str) -> float:
    value = answer.get(key)
    if not isinstance(value, (int, float)):
        raise jev.JevError(f"{question_id}: expected a numeric {key!r}")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise jev.JevError(f"{question_id}: {key} outside [0, 1]")
    return value


def decide(task: str, claims: Sequence[Mapping[str, Any]], *,
           caller: Optional[Caller] = None,
           policy: Policy = Policy(),
           budget_bytes: int = DEFAULT_BUDGET_BYTES,
           include_status: bool = False,
           timeout: float = 30.0) -> Decision:
    """Ask Jev one question set, then apply the deterministic policy."""
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    if caller is None:
        def caller(state: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            return jev.ask(state, questions, consent=True, timeout=timeout)

    state = render_state(task, claims, include_status=include_status)
    questions = build_questions(claims)
    started = time.monotonic()
    parsed = caller(state, questions)
    latency_ms = int((time.monotonic() - started) * 1000)

    contradiction = _prob(jev.answer(parsed, "contradiction"), "noul", "contradiction")
    governing_answer = jev.answer(parsed, "governing")
    governing = governing_answer.get("choice")
    governing_confidence = governing_answer.get("confidence")
    if governing == "none":
        governing = None
    confidence_value = (
        float(governing_confidence)
        if isinstance(governing_confidence, (int, float)) else None
    )

    raw: List[Entry] = []
    for claim in claims:
        claim_id = str(claim["claim_id"])
        applies = _prob(jev.answer(parsed, f"applies::{claim_id}"), "noul", claim_id)
        holds = _prob(jev.answer(parsed, f"holds::{claim_id}"), "noul", claim_id)
        score = applies * holds
        is_governing = (
            governing == claim_id
            and confidence_value is not None
            and confidence_value >= policy.governing_at
        )
        raw.append(Entry(
            claim_id=claim_id, text=str(claim["text"]),
            p_applies=applies, p_holds=holds, score=score,
            action=policy.action(score, contradiction=contradiction,
                                 governing=is_governing),
            included=False, governing=is_governing,
        ))

    # Byte budget: rank by score, fill until the budget is spent. Excluded
    # entries never consume budget.
    order = sorted(range(len(raw)), key=lambda i: raw[i].score, reverse=True)
    included = [False] * len(raw)
    used = 0
    omitted = 0
    for index in order:
        entry = raw[index]
        if entry.action == EXCLUDE:
            continue
        size = len(f"- {entry.claim_id}: {entry.text}\n".encode("utf-8"))
        if used + size > budget_bytes:
            omitted += 1
            continue
        used += size
        included[index] = True

    entries = [
        Entry(e.claim_id, e.text, e.p_applies, e.p_holds, e.score, e.action,
              included[i], e.governing)
        for i, e in enumerate(raw)
    ]
    return Decision(
        task=task, model=str(parsed.get("model", "?")),
        policy=policy.to_dict(), entries=entries,
        contradiction=contradiction, governing=governing,
        governing_confidence=confidence_value,
        used_bytes=used, budget_bytes=budget_bytes, omitted=omitted,
        latency_ms=latency_ms, usage=dict(parsed.get("usage") or {}),
    )
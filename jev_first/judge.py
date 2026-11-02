"""The judgment engine: contract-driven questions, one request, typed output."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from chat_distiller import jev

from .contracts import question as contract_question
from .contracts import questions as question_set
from .cache import Cache, input_hash
from .policy import ADMIT, EXCLUDE, REVIEW, Policy
from .questions import render_state

Caller = Callable[[str, Mapping[str, Mapping[str, Any]]], Mapping[str, Any]]
DEFAULT_BUDGET_BYTES = 2048
MAX_RECORDS = 6


@dataclass(frozen=True)
class Entry:
    record_id: str
    text: str
    action: str
    confidence: Optional[float]
    p_admit: Optional[float]
    governing: bool
    included: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "text": self.text,
            "action": self.action,
            "confidence": (round(self.confidence, 4)
                           if self.confidence is not None else None),
            "p_admit": (round(self.p_admit, 4)
                        if self.p_admit is not None else None),
            "governing": self.governing,
            "included": self.included,
        }


@dataclass(frozen=True)
class Judgment:
    task: str
    model: str
    question_set_version: str
    policy: Dict[str, Any]
    input_hash: str
    entries: Sequence[Entry]
    contradiction: float
    governing: Optional[str]
    governing_confidence: Optional[float]
    used_bytes: int
    budget_bytes: int
    omitted: int
    latency_ms: int
    usage: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    degraded: bool = False
    cached: bool = False

    @property
    def admitted(self) -> List[Entry]:
        return [e for e in self.entries if e.included]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "model": self.model,
            "question_set_version": self.question_set_version,
            "policy": self.policy,
            "input_hash": self.input_hash,
            "contradiction": round(self.contradiction, 4),
            "governing": self.governing,
            "governing_confidence": (
                round(self.governing_confidence, 4)
                if self.governing_confidence is not None else None),
            "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes,
            "omitted": self.omitted,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "created_at": self.created_at,
            "degraded": self.degraded,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, body: Dict[str, Any]) -> "Judgment":
        entries = [Entry(
            record_id=e["record_id"], text=e.get("text", ""),
            action=e["action"], confidence=e.get("confidence"),
            p_admit=e.get("p_admit"), governing=e.get("governing", False),
            included=e.get("included", False),
        ) for e in body["entries"]]
        return cls(
            task=body["task"], model=body["model"],
            question_set_version=body["question_set_version"],
            policy=body["policy"], input_hash=body["input_hash"],
            entries=entries, contradiction=body["contradiction"],
            governing=body.get("governing"),
            governing_confidence=body.get("governing_confidence"),
            used_bytes=body["used_bytes"], budget_bytes=body["budget_bytes"],
            omitted=body["omitted"], latency_ms=body["latency_ms"],
            usage=body.get("usage") or {}, created_at=body.get("created_at", ""),
            degraded=body.get("degraded", False), cached=True,
        )


def _build_questions(records: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    spec = question_set()
    admit = spec["questions"]["admit"]
    contradiction = spec["questions"]["contradiction"]
    governing = spec["questions"]["governing"]
    questions: Dict[str, Dict[str, Any]] = {}
    for record in records:
        questions[f"admit::{record['record_id']}"] = {
            "type": admit["type"], "instructions": admit["instructions"],
            "criteria": dict(admit["criteria"]),
        }
    questions["contradiction"] = {"type": "noul",
                                  "instructions": contradiction["instructions"]}
    criteria = {r["record_id"]: str(r["text"])[:160] for r in records}
    criteria["none"] = "No single claim governs this task"
    questions["governing"] = {"type": "choice",
                              "instructions": governing["instructions"],
                              "criteria": criteria}
    return questions


def _num(value: Any, question_id: str) -> float:
    if not isinstance(value, (int, float)):
        raise jev.JevError(f"{question_id}: expected a number")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise jev.JevError(f"{question_id}: outside [0, 1]")
    return value


def _pack(entries: List[Entry], budget_bytes: int) -> tuple:
    """Rank non-excluded entries by p(admit), fill until the budget is spent."""
    used = 0
    omitted = 0
    included: Dict[str, bool] = {e.record_id: False for e in entries}
    for entry in sorted((e for e in entries if e.action != EXCLUDE),
                        key=lambda e: (e.p_admit or 0.0), reverse=True):
        size = len(f"- {entry.record_id}: {entry.text}\n".encode("utf-8"))
        if used + size > budget_bytes:
            omitted += 1
            continue
        used += size
        included[entry.record_id] = True
    return used, omitted, included


def judge(task: str, records: Sequence[Mapping[str, Any]], *,
          caller: Optional[Caller] = None,
          policy: Policy = Policy(),
          budget_bytes: int = DEFAULT_BUDGET_BYTES,
          on_error: str = "review",
          cache: Optional[Cache] = None,
          model: Optional[str] = None,
          timeout: float = 30.0) -> Judgment:
    """Judge a candidate record set against a task. One request, N+2 questions."""
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    if on_error not in ("raise", "review"):
        raise ValueError('on_error must be "raise" or "review"')
    if not records:
        raise ValueError("at least one record is required")
    if len(records) > MAX_RECORDS:
        raise ValueError(f"too many records for one request (max {MAX_RECORDS})")

    spec = question_set()
    questions = _build_questions(records)
    state = render_state(task, records)
    resolved_model = model or jev.model_name()
    key = input_hash(task, list(records), questions, model=resolved_model,
                     question_set_version=spec["version"])

    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return Judgment.from_dict(hit)

    if caller is None:
        def caller(state: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            return jev.ask(state, questions, consent=True, timeout=timeout, model=model)

    started = time.monotonic()
    try:
        parsed = caller(state, questions)
    except jev.JevError:
        if on_error == "raise":
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        used, omitted, included = _pack(
            [Entry(r["record_id"], str(r["text"]), REVIEW, None, None, False, False)
             for r in records], budget_bytes)
        return Judgment(
            task=task, model="unavailable",
            question_set_version=spec["version"], policy=policy.to_dict(),
            input_hash=key,
            entries=[Entry(r["record_id"], str(r["text"]), REVIEW, None, None,
                           False, included[r["record_id"]]) for r in records],
            contradiction=0.0, governing=None, governing_confidence=None,
            used_bytes=used, budget_bytes=budget_bytes, omitted=omitted,
            latency_ms=latency_ms, created_at=datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"), degraded=True,
        )
    latency_ms = int((time.monotonic() - started) * 1000)

    contradiction = _num(jev.answer(parsed, "contradiction").get("noul"), "contradiction")
    governing_answer = jev.answer(parsed, "governing")
    governing = governing_answer.get("choice")
    governing_confidence = governing_answer.get("confidence")
    if governing == "none":
        governing = None
    governing_value = (float(governing_confidence)
                       if isinstance(governing_confidence, (int, float)) else None)

    entries: List[Entry] = []
    for record in records:
        record_id = str(record["record_id"])
        answer = jev.answer(parsed, f"admit::{record_id}")
        choice = answer.get("choice")
        if choice not in (ADMIT, REVIEW, EXCLUDE):
            raise jev.JevError(f"admit::{record_id}: unknown choice {choice!r}")
        probabilities = answer.get("probabilities") or {}
        confidence = answer.get("confidence")
        is_governing = (governing == record_id
                        and governing_value is not None
                        and governing_value >= policy.governing_at)
        action = policy.action(choice, contradiction=contradiction,
                               governing=is_governing)
        entries.append(Entry(
            record_id=record_id, text=str(record["text"]), action=action,
            confidence=(float(confidence)
                        if isinstance(confidence, (int, float)) else None),
            p_admit=(float(probabilities.get(ADMIT, 0.0))
                     if isinstance(probabilities.get(ADMIT), (int, float)) else None),
            governing=is_governing, included=False,
        ))

    used, omitted, included = _pack(entries, budget_bytes)
    entries = [Entry(e.record_id, e.text, e.action, e.confidence, e.p_admit,
                     e.governing, included[e.record_id]) for e in entries]

    judgment = Judgment(
        task=task, model=str(parsed.get("model", "?")),
        question_set_version=spec["version"], policy=policy.to_dict(),
        input_hash=key, entries=entries, contradiction=contradiction,
        governing=governing, governing_confidence=governing_value,
        used_bytes=used, budget_bytes=budget_bytes, omitted=omitted,
        latency_ms=latency_ms, usage=dict(parsed.get("usage") or {}),
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # Only successful judgments enter the cache. A degraded decision must be
    # re-judged once the transport recovers, never replayed.
    if cache is not None:
        cache.put(key, judgment.to_dict())
    return judgment
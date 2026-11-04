"""The judgment engine: two stages, every question from the frozen contract.

Stage 1 — one `admit` choice per record, against a **single-record state**.
  The record is judged alone with the task, so a contradiction elsewhere in the
  set cannot contaminate its answer (this is why the retired applies/holds pair
  existed, and why the one-big-request flow hedged everything to review).

Stage 2 — the validated `relation` question on every pair that touches a
non-excluded record (admitted or review, plus its excluded counterpart).
  Pair states are exactly the frozen 30-pair format and are **task-independent**,
  so pair judgments cache across every future task. A confirmed contradicting
  pair sends both records to review; everything else keeps its stage-1 action.
  The global contradiction signal is retired from the flow: pairwise is strictly
  more informative and cannot punish uninvolved records.

Stage 3 — `governing` over the surviving set; may promote review to admit,
  never a conflicted record.

Failures fail open: a record or pair we could not judge goes to review. An
outage must never look like a clean admission.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from chat_distiller import jev

from .cache import Cache, input_hash
from .contracts import questions as question_set
from .policy import ADMIT, EXCLUDE, REVIEW, Policy

Caller = Callable[[str, Mapping[str, Mapping[str, Any]]], Mapping[str, Any]]
DEFAULT_BUDGET_BYTES = 2048
MAX_RECORDS = 6


def _canonical(body: Mapping[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@dataclass(frozen=True)
class Entry:
    record_id: str
    text: str
    action: str
    confidence: Optional[float]
    p_admit: Optional[float]
    governing: bool
    conflicted: bool
    low_margin: bool
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
            "conflicted": self.conflicted,
            "low_margin": self.low_margin,
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
    conflicts: Sequence[Sequence[str]]
    uncertain_pairs: Sequence[Sequence[str]]
    pair_checks: int
    governing: Optional[str]
    governing_confidence: Optional[float]
    used_bytes: int
    budget_bytes: int
    omitted: int
    latency_ms: int
    requests: int
    usage: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    degraded: bool = False
    cached: bool = False
    selection: Dict[str, Any] = field(default_factory=dict)

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
            "conflicts": [list(pair) for pair in self.conflicts],
            "uncertain_pairs": [list(pair) for pair in self.uncertain_pairs],
            "pair_checks": self.pair_checks,
            "governing": self.governing,
            "governing_confidence": (
                round(self.governing_confidence, 4)
                if self.governing_confidence is not None else None),
            "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes,
            "omitted": self.omitted,
            "latency_ms": self.latency_ms,
            "requests": self.requests,
            "usage": self.usage,
            "created_at": self.created_at,
            "degraded": self.degraded,
            "selection": self.selection,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, body: Dict[str, Any]) -> "Judgment":
        entries = [Entry(
            record_id=e["record_id"], text=e.get("text", ""),
            action=e["action"], confidence=e.get("confidence"),
            p_admit=e.get("p_admit"), governing=e.get("governing", False),
            conflicted=e.get("conflicted", False),
            low_margin=e.get("low_margin", False),
            included=e.get("included", False),
        ) for e in body["entries"]]
        return cls(
            task=body["task"], model=body["model"],
            question_set_version=body["question_set_version"],
            policy=body["policy"], input_hash=body["input_hash"],
            entries=entries, conflicts=body.get("conflicts", []),
            uncertain_pairs=body.get("uncertain_pairs", []),
            pair_checks=body.get("pair_checks", 0),
            governing=body.get("governing"),
            governing_confidence=body.get("governing_confidence"),
            used_bytes=body["used_bytes"], budget_bytes=body["budget_bytes"],
            omitted=body["omitted"], latency_ms=body["latency_ms"],
            requests=body.get("requests", 0), usage=body.get("usage") or {},
            created_at=body.get("created_at", ""),
            degraded=body.get("degraded", False), cached=True,
            selection=body.get("selection") or {},
        )


def _margin(probabilities: Mapping[str, Any]) -> Optional[float]:
    """Gap between the top-two options; None when we cannot compute it."""
    values = sorted((float(v) for v in probabilities.values()
                     if isinstance(v, (int, float))), reverse=True)
    if len(values) < 2:
        return None
    return values[0] - values[1]


def _pack(entries: List[Entry], budget_bytes: int) -> tuple:
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
          max_workers: int = 4,
          timeout: float = 30.0) -> Judgment:
    """Judge a candidate record set against a task.

    Fresh cost: N admit requests + C(a,2) relation requests + 1 governing
    request, run concurrently. Per-record and per-pair inputs are cached, so a
    repeated task is served without the network and a repeated pair is served
    across every future task. Only clean judgments are cached; a degraded one
    must be re-judged after the transport recovers.
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    if on_error not in ("raise", "review"):
        raise ValueError('on_error must be "raise" or "review"')
    if not records:
        raise ValueError("at least one record is required")
    if len(records) > MAX_RECORDS:
        raise ValueError(f"too many records for one decision (max {MAX_RECORDS})")

    spec = question_set()
    admit_spec = spec["questions"]["admit"]
    governing_spec = spec["questions"]["governing"]
    relation_spec = spec["questions"]["relation"]
    relation_question = {"type": relation_spec["type"],
                         "instructions": relation_spec["instructions"],
                         "criteria": dict(relation_spec["criteria"])}
    resolved_model = model or jev.model_name()
    version = spec["version"]

    top_key = input_hash(task, list(records), {
        "admit": admit_spec,
        "relation": relation_question,
        "relation_scope": "pairs_touching_non_excluded",
    }, model=resolved_model, question_set_version=version)
    if cache is not None:
        hit = cache.get(top_key)
        if hit is not None and not hit.get("degraded"):
            return Judgment.from_dict(hit)

    started = time.monotonic()
    counter = {"requests": 0, "degraded": False}
    lock = threading.Lock()

    def ask(state: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
        key = input_hash(state, [], questions, model=resolved_model,
                         question_set_version=version)
        if cache is not None:
            hit = cache.get(key)
            if hit is not None:
                return hit
        parsed = dict(caller(state, questions))
        with lock:
            counter["requests"] += 1
        if cache is not None:
            cache.put(key, parsed)
        return parsed

    if caller is None:
        def caller(state: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            return jev.ask(state, questions, consent=True, timeout=timeout,
                           model=model)

    def reviewed(record_id: str, text: str) -> Entry:
        return Entry(record_id, text, REVIEW, None, None, False, False, False, False)

    # ---- stage 1: one admit choice per record, judged alone -----------------
    def admit_job(record: Mapping[str, Any]) -> Entry:
        record_id = str(record["record_id"])
        text = str(record["text"])
        state = f"TASK: {task.strip()}\n\nCLAIM:\n- {record_id}: {text}"
        questions = {"admit": {"type": admit_spec["type"],
                               "instructions": admit_spec["instructions"],
                               "criteria": dict(admit_spec["criteria"])}}
        try:
            parsed = ask(state, questions)
        except jev.JevError:
            if on_error == "raise":
                raise
            with lock:
                counter["degraded"] = True
            return reviewed(record_id, text)
        answer = jev.answer(parsed, "admit")
        choice = answer.get("choice")
        if choice not in (ADMIT, REVIEW, EXCLUDE):
            raise jev.JevError(f"admit::{record_id}: unknown choice {choice!r}")
        probabilities = answer.get("probabilities") or {}
        confidence = answer.get("confidence")
        margin = _margin(probabilities)
        thin = margin is None or margin < policy.margin
        return Entry(
            record_id=record_id, text=text,
            action=policy.action(choice, thin_margin=thin),
            confidence=(float(confidence)
                        if isinstance(confidence, (int, float)) else None),
            p_admit=(float(probabilities.get(ADMIT, 0.0))
                     if isinstance(probabilities.get(ADMIT), (int, float)) else None),
            governing=False, conflicted=False, low_margin=thin, included=False,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(records)))) as pool:
        entries: List[Entry] = list(pool.map(admit_job, records))

    # An excluded record can still contradict an admitted one. Stage 1 answers
    # relevance, not truth, so a contradiction must be checked whenever either
    # side is non-excluded. Excluded-excluded pairs stay unchecked: neither is
    # relevant to this task.
    pairs = [(a, b) for a, b in combinations(entries, 2)
             if a.action != EXCLUDE or b.action != EXCLUDE]

    # ---- stage 2: localize conflicts with the validated pair question -------
    conflicts: List[List[str]] = []
    uncertain_pairs: List[List[str]] = []
    conflicted_ids: Dict[str, bool] = {}
    uncertain_ids: Dict[str, bool] = {}
    unknown_ids: Dict[str, bool] = {}
    pair_checks = 0

    def relation_job(pair: tuple) -> tuple:
        a, b = pair
        state = f"Statement A: {a.text}\nStatement B: {b.text}"
        try:
            parsed = ask(state, {"relation": relation_question})
        except jev.JevError:
            if on_error == "raise":
                raise
            with lock:
                counter["degraded"] = True
            return pair, None, None
        answer = jev.answer(parsed, "relation")
        probabilities = answer.get("probabilities") or {}
        observed = (max(probabilities, key=probabilities.get)
                    if probabilities else answer.get("choice"))
        margin = _margin(probabilities)
        return pair, observed, margin

    if pairs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(pairs)))) as pool:
            results = list(pool.map(relation_job, pairs))
        pair_checks = len(pairs)
        for (a, b), observed, margin in results:
            if observed is None:
                unknown_ids[a.record_id] = True
                unknown_ids[b.record_id] = True
                continue
            # A confirmed contradiction needs a margin, not just an argmax:
            # borderline pairs are exactly where sampling flips (~17% on the
            # 'must' pair, borderline-stability.json).
            if observed == "contradiction" and margin is not None \
                    and margin >= policy.margin:
                conflicts.append([a.record_id, b.record_id])
                conflicted_ids[a.record_id] = True
                conflicted_ids[b.record_id] = True
            elif margin is None or margin < policy.margin:
                uncertain_ids[a.record_id] = True
                uncertain_ids[b.record_id] = True
                uncertain_pairs.append([a.record_id, b.record_id])
    entries = [Entry(
        e.record_id, e.text,
        REVIEW if (e.record_id in conflicted_ids or e.record_id in unknown_ids
                   or e.record_id in uncertain_ids) else e.action,
        e.confidence, e.p_admit, e.governing,
        e.record_id in conflicted_ids,
        e.low_margin or e.record_id in uncertain_ids, e.included,
    ) for e in entries]

    # ---- stage 3: governing over the surviving set --------------------------
    governing: Optional[str] = None
    governing_value: Optional[float] = None
    survivors = [e for e in entries if e.action != EXCLUDE]
    if len(survivors) >= 2:
        state = (f"TASK: {task.strip()}\n\nMEMORY CLAIMS:\n"
                 + "\n".join(f"- {e.record_id}: {e.text}" for e in survivors))
        questions = {"governing": {
            "type": governing_spec["type"],
            "instructions": governing_spec["instructions"],
            "criteria": {**{e.record_id: e.text[:160] for e in survivors},
                         "none": "No single claim governs this task"}}}
        try:
            parsed = ask(state, questions)
        except jev.JevError:
            if on_error == "raise":
                raise
            # Governing is an enhancement, never a safety input: without it
            # the survivors keep their stage-1/2 actions and the result is
            # flagged degraded.
            with lock:
                counter["degraded"] = True
            parsed = None
        if parsed is not None:
            answer = jev.answer(parsed, "governing")
            governing = answer.get("choice")
            governing_confidence = answer.get("confidence")
            if governing == "none":
                governing = None
            governing_value = (float(governing_confidence)
                               if isinstance(governing_confidence, (int, float))
                               else None)

    entries = [Entry(
        e.record_id, e.text,
        ADMIT if (governing == e.record_id and governing_value is not None
                  and governing_value >= policy.governing_at
                  and e.action == REVIEW and not e.conflicted) else e.action,
        e.confidence, e.p_admit,
        governing == e.record_id and governing_value is not None
        and governing_value >= policy.governing_at,
        e.conflicted, e.low_margin, e.included,
    ) for e in entries]

    used, omitted, included = _pack(entries, budget_bytes)
    entries = [Entry(e.record_id, e.text, e.action, e.confidence, e.p_admit,
                     e.governing, e.conflicted, e.low_margin,
                     included[e.record_id])
               for e in entries]

    latency_ms = int((time.monotonic() - started) * 1000)
    # If nothing at all was answered, "model" would be a lie: nothing ran.
    model_field = (resolved_model if counter["requests"]
                   else "unavailable" if counter["degraded"] else resolved_model)
    judgment = Judgment(
        task=task, model=model_field, question_set_version=version,
        policy=policy.to_dict(),
        input_hash=top_key,
        entries=entries, conflicts=conflicts, uncertain_pairs=uncertain_pairs,
        pair_checks=pair_checks,
        governing=governing, governing_confidence=governing_value,
        used_bytes=used, budget_bytes=budget_bytes, omitted=omitted,
        latency_ms=latency_ms, requests=counter["requests"],
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        degraded=counter["degraded"],
    )
    if cache is not None and not judgment.degraded:
        cache.put(top_key, judgment.to_dict())
    return judgment
"""Optional TypeSafe / Jev (System One) client.

Zero third-party dependencies. Disabled unless ``TYPESAFE_API_KEY`` is present
and the caller passes ``consent=True``.

Privacy boundary: calling this module sends ``state`` text to a third party.
That is a deliberate departure from this repository's default "no network"
guarantee, so the call sites must be explicit and the README qualifies the
guarantee accordingly. Credentials are read from the environment and are never
written to disk, logged, or included in an exception message.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional, Sequence

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "TYPESAFE_MODEL"


class JevError(RuntimeError):
    """A request could not be built, sent, or understood."""


def api_key() -> Optional[str]:
    value = os.environ.get(API_KEY_ENV, "").strip()
    return value or None


def model_name() -> str:
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def configured() -> bool:
    """True when a credential is present. Never returns the credential."""
    return api_key() is not None


def choice(instructions: str, criteria: Mapping[str, str]) -> Dict[str, Any]:
    if not criteria:
        raise JevError("choice requires at least one criterion")
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(instructions: str, criteria: Sequence[str]) -> Dict[str, Any]:
    if not criteria:
        raise JevError("score requires at least one level")
    return {"type": "score", "instructions": instructions, "criteria": list(criteria)}


def noul(instructions: str) -> Dict[str, Any]:
    return {"type": "noul", "instructions": instructions}


def build_request(state: str, questions: Mapping[str, Mapping[str, Any]],
                  model: Optional[str] = None) -> Dict[str, Any]:
    """Validate and assemble a request body. Raises before any network I/O."""
    if not isinstance(state, str) or not state.strip():
        raise JevError("state must be a non-empty string")
    if not questions:
        raise JevError("at least one question is required")
    allowed = {"type", "instructions", "criteria"}
    for key, question in questions.items():
        if not isinstance(key, str) or not key:
            raise JevError("question ids must be non-empty strings")
        extra = set(question) - allowed
        if extra:
            raise JevError(f"{key}: unsupported question fields: {sorted(extra)}")
        kind = question.get("type")
        if kind not in ("choice", "score", "noul"):
            raise JevError(f"{key}: unknown question type: {kind!r}")
        if not isinstance(question.get("instructions"), str) or not question["instructions"].strip():
            raise JevError(f"{key}: instructions must be a non-empty string")
        if kind == "noul" and "criteria" in question:
            raise JevError(f"{key}: noul takes no criteria")
        if kind in ("choice", "score") and not question.get("criteria"):
            raise JevError(f"{key}: {kind} requires criteria")
    return {"state": state, "model": model or model_name(), "questions": dict(questions)}


def ask(state: str, questions: Mapping[str, Mapping[str, Any]], *,
        consent: bool = False, timeout: float = 30.0,
        url: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Send one System One request and return ``{model, answers, usage}``.

    ``consent`` must be True: the state text leaves this machine.
    """
    if not consent:
        raise JevError("consent=True is required: state text is sent to a third party")
    key = api_key()
    if key is None:
        raise JevError(f"{API_KEY_ENV} is not set")
    body = build_request(state, questions, model=model)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url or os.environ.get("TYPESAFE_URL", DEFAULT_URL),
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:400]
        except Exception:  # pragma: no cover - best effort only
            pass
        raise JevError(f"HTTP {exc.code}: {detail or exc.reason}") from None
    except OSError as exc:
        # URLError, socket timeouts and connection resets all land here.
        raise JevError(f"transport failure: {exc}") from None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JevError(f"response is not UTF-8 JSON: {exc}") from None
    if not isinstance(parsed, dict) or "answers" not in parsed:
        raise JevError("response has no answers object")
    return parsed


def answer(parsed: Mapping[str, Any], question_id: str) -> Dict[str, Any]:
    """Return one answer, raising a typed error instead of KeyError."""
    answers = parsed.get("answers")
    if not isinstance(answers, dict) or question_id not in answers:
        raise JevError(f"no answer for question: {question_id}")
    value = answers[question_id]
    if not isinstance(value, dict):
        raise JevError(f"answer {question_id} is not an object")
    return value
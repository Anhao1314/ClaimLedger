"""Load and enforce the frozen contracts.

The contracts are the product definition:

* ``contracts/questions.v3.json`` — the typed question set (the IP).
  ``questions.v1.json`` and ``questions.v2.json`` stay on disk as frozen
  historical sets; the active set is v3, which adds the validated
  ``replacement`` and ``direction`` questions for the directed edge plane.
* ``contracts/records.v1.json``   — what a memory record is (no stored status).
* ``contracts/manifest.json``     — sha256 over exact file bytes.

Changing a contract is a version bump, never an edit.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts"
QUESTION_SETS = {"v1": "questions.v1.json", "v2": "questions.v2.json",
                 "v3": "questions.v3.json"}
ACTIVE_QUESTION_SET = "v3"
QUESTIONS_V1_FILE = CONTRACT_DIR / QUESTION_SETS["v1"]
QUESTIONS_V2_FILE = CONTRACT_DIR / QUESTION_SETS["v2"]
QUESTIONS_FILE = CONTRACT_DIR / QUESTION_SETS[ACTIVE_QUESTION_SET]
RECORDS_FILE = CONTRACT_DIR / "records.v1.json"
MANIFEST_FILE = CONTRACT_DIR / "manifest.json"

GENESIS_HASH = "0" * 64
_CANONICAL = dict(ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ContractError(RuntimeError):
    """A contract file is missing, tampered with, or a record violates it."""


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"missing contract: {path.name}") from None
    except json.JSONDecodeError as exc:
        raise ContractError(f"{path.name}: not valid JSON: {exc}") from None


def verify_manifest() -> Dict[str, str]:
    """Recompute sha256 for each contract file and compare with the manifest."""
    manifest = _read(MANIFEST_FILE)
    status = {}
    for name, expected in manifest["files"].items():
        path = CONTRACT_DIR / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected["sha256"]:
            raise ContractError(
                f"{name}: hash mismatch (contract changed without a version bump)")
        status[name] = "ok"
    return status


def questions(version: str = ACTIVE_QUESTION_SET) -> Dict[str, Any]:
    if version not in QUESTION_SETS:
        raise ContractError(f"unknown question set version: {version}")
    return _read(CONTRACT_DIR / QUESTION_SETS[version])


def records_schema() -> Dict[str, Any]:
    return _read(RECORDS_FILE)


def question(name: str) -> Dict[str, Any]:
    entry = questions()["questions"].get(name)
    if entry is None:
        raise ContractError(f"question not in contract: {name}")
    return entry


def relation_question() -> Dict[str, Any]:
    """The validated pair question, ready for ``jev.ask``."""
    entry = question("relation")
    return {"type": entry["type"], "instructions": entry["instructions"],
            "criteria": dict(entry["criteria"])}


def edge_question() -> Dict[str, Any]:
    """The validated edge-classification question, ready for ``jev.ask``."""
    entry = question("edge")
    return {"type": entry["type"], "instructions": entry["instructions"],
            "criteria": dict(entry["criteria"])}


def replacement_question() -> Dict[str, Any]:
    """The validated contradicts-disambiguation question, ready for ``jev.ask``."""
    entry = question("replacement")
    return {"type": entry["type"], "instructions": entry["instructions"],
            "criteria": dict(entry["criteria"])}


def direction_question() -> Dict[str, Any]:
    """The validated supersedes-direction question, ready for ``jev.ask``."""
    entry = question("direction")
    return {"type": entry["type"], "instructions": entry["instructions"],
            "criteria": dict(entry["criteria"])}


def canonical_body(text: str, source: str, at: str, scope: Optional[str]) -> str:
    body = {"text": text, "source": source, "at": at, "scope": scope}
    return json.dumps(body, **_CANONICAL)


def make_record(text: str, source: str, at: str, *,
                scope: Optional[str] = None,
                prev_hash: str = GENESIS_HASH) -> Dict[str, Any]:
    """Build one record exactly as records.v1.json defines it."""
    body = canonical_body(text, source, at, scope)
    record_id = "rec_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
    return {"record_id": record_id, "text": text, "source": source,
            "at": at, "scope": scope, "prev_hash": prev_hash}


def validate_record(record: Mapping[str, Any]) -> None:
    """Raise ``ContractError`` unless the record satisfies records.v1.json."""
    schema = records_schema()
    absent = schema["absent_by_design"]
    present_absent = [field for field in absent if field in record]
    if present_absent:
        raise ContractError(
            f"record carries fields that are judgments, not data: {present_absent}")
    for field in ("record_id", "text", "source", "at", "prev_hash"):
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise ContractError(f"record field {field} must be a non-empty string")
    if not re.fullmatch(r"rec_[0-9a-f]{24}", record["record_id"]):
        raise ContractError("record_id must be rec_ + 24 hex chars")
    if not re.fullmatch(r"[0-9a-f]{64}", record["prev_hash"]):
        raise ContractError("prev_hash must be 64 hex chars")
    expected = "rec_" + hashlib.sha256(
        canonical_body(record["text"], record["source"], record["at"],
                       record.get("scope")).encode("utf-8")).hexdigest()[:24]
    if record["record_id"] != expected:
        raise ContractError("record_id does not match the canonical body")
    if record["text"] != record["text"].strip() or not record["text"].strip():
        raise ContractError("text must be non-empty and stripped")
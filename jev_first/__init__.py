"""Jev-first memory: contracts → records → judgments → views.

The product layers, in order of authority:

* ``contracts/`` — the frozen question set and record schema (the IP)
* ``records.py`` — append-only, hash-chained record store (no stored status)
* ``judge.py``   — contract-driven judgment engine (one request per decision)
* ``policy.py``  — deterministic action rules (no score formula)
* ``log.py``     — sealed judgment log (hash-chained)
* ``cache.py``   — judgment cache keyed by the full input

None of these depend on which generation model is running.
"""
from .cache import Cache
from .contracts import (ContractError, make_record, relation_question,
                        validate_record, verify_manifest)
from .judge import Entry, Judgment, judge
from .log import append_judgment, verify as verify_log
from .log import read as read_log
from .policy import ADMIT, EXCLUDE, REVIEW, Policy
from .questions import render_state
from .records import RecordStore
from .select import select_candidates

__all__ = [
    "ADMIT", "EXCLUDE", "REVIEW",
    "Cache", "ContractError", "Entry", "Judgment", "Policy", "RecordStore",
    "append_judgment", "judge", "make_record", "read_log",
    "relation_question", "render_state", "select_candidates",
    "validate_record",
    "verify_log", "verify_manifest",
]
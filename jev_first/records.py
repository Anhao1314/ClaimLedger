"""Append-only record store per contracts/records.v1.json.

Records carry text, source, time, scope and a hash chain — and nothing else.
Whether a record still holds is a judgment, never a stored field.

Chain semantics: ``record[N].prev_hash = body_hash(record[N-1])``, where
``body_hash`` is sha256 over the record's own canonical JSON (which already
contains its own ``prev_hash``). Genesis is 64 zeros.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import ContractError, make_record, validate_record

GENESIS = "0" * 64

# Near-duplicate detection is deterministic and local: no model call at write
# time. It exists because content addressing only catches byte-identical text;
# two agents will describe the same decision differently.
NEAR_DUPLICATE_THRESHOLD = 0.65
NEAR_DUPLICATE_MIN_SHARED = 4
NEAR_DUPLICATE_MIN_JACCARD = 0.5
_STOPWORDS = frozenset(
    "the a an of to for in on at by with and or is are was were be been "
    "this that it its as from always".split())
_NEGATIONS = frozenset(
    "not no never cannot without banned ban forbid forbidden prohibit "
    "prohibited".split())
_CJK_NEGATIONS = ("不", "不是", "而非", "禁止", "不得", "不要", "无需", "不准")
_LATIN_WORD = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _similarity_tokens(text: str) -> set:
    """Latin words (crudely singularized) plus CJK character bigrams."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = set()
    for word in _LATIN_WORD.findall(normalized):
        if word in _STOPWORDS or (len(word) < 2 and not word.isdigit()):
            continue
        if (word.endswith("s") and not word.endswith(("ss", "us", "is"))
                and len(word) > 4):
            word = word[:-1]
        tokens.add(word)
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _is_negated(text: str, tokens: set) -> bool:
    return bool(tokens & _NEGATIONS) or any(
        marker in text for marker in _CJK_NEGATIONS)


def find_near_duplicate(records: List[Dict[str, Any]], text: str, *,
                        scope: Optional[str] = None,
                        threshold: float = NEAR_DUPLICATE_THRESHOLD,
                        min_shared: int = NEAR_DUPLICATE_MIN_SHARED,
                        min_jaccard: float = NEAR_DUPLICATE_MIN_JACCARD
                        ) -> Optional[tuple]:
    """Return ``(record, similarity)`` for the closest paraphrased decision.

    Deliberately conservative: short texts are skipped, negation parity must
    match, and a minimum number of content tokens must overlap. A miss is
    cheaper than silently merging two different decisions.
    """
    target = _similarity_tokens(text)
    if len(target) < min_shared:
        return None
    target_negated = _is_negated(text, target)

    def scores(a: set, b: set):
        shared = a & b
        if len(shared) < min_shared:
            return None
        return (len(shared) / min(len(a), len(b)),
                len(shared) / len(a | b))

    best = None
    for record in records:
        if (record.get("scope") or None) != (scope or None):
            continue
        other = _similarity_tokens(str(record.get("text", "")))
        if len(other) < min_shared:
            continue
        if _is_negated(str(record.get("text", "")), other) != target_negated:
            continue
        candidates = []
        full = scores(target, other)
        if full:
            candidates.append(full)
        # Mixed-language records (Chinese sentence, English technical terms)
        # should still match their English paraphrase: compare the Latin
        # subset as a second view instead of letting CJK bigrams dilute it.
        latin_target = {t for t in target if t.isascii()}
        latin_other = {t for t in other if t.isascii()}
        if len(latin_target) >= min_shared and len(latin_other) >= min_shared:
            latin = scores(latin_target, latin_other)
            if latin:
                candidates.append(latin)
        if not candidates:
            continue
        score = max(candidates)
        if score[0] < threshold or score[1] < min_jaccard:
            continue
        if best is None or score > best[0]:
            best = (score, record, score[0])
    if best is None:
        return None
    return best[1], round(best[2], 3)


def body_hash(record: Dict[str, Any]) -> str:
    """sha256 over the record's canonical JSON, all fields included."""
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordStore:
    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)

    def append(self, text: str, source: str, *, at: Optional[str] = None,
               scope: Optional[str] = None) -> Dict[str, Any]:
        if at is None:
            at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = make_record(text, source, at, scope=scope,
                             prev_hash=self.last_hash())
        # Content-addressed identity means an exact repeat would corrupt the
        # store on load (duplicate record_id). Refuse it here, at the write.
        if any(r["record_id"] == record["record_id"] for r in self.load()):
            raise ContractError(
                f"duplicate record: {record['record_id']} already exists "
                f"({text[:60]!r})")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def load(self) -> List[Dict[str, Any]]:
        """Load and verify the whole chain. Raises on any tampering."""
        if not self.path.exists():
            return []
        records: List[Dict[str, Any]] = []
        expected_prev: str = GENESIS
        with open(self.path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ContractError(f"{self.path}:{lineno}: not JSON") from exc
                try:
                    validate_record(record)
                except ContractError as exc:
                    raise ContractError(f"{self.path}:{lineno}: {exc}") from None
                if record["prev_hash"] != expected_prev:
                    raise ContractError(f"{self.path}:{lineno}: broken hash chain")
                if any(r["record_id"] == record["record_id"] for r in records):
                    raise ContractError(f"{self.path}:{lineno}: duplicate record_id")
                records.append(record)
                expected_prev = body_hash(record)
        return records

    def last_hash(self) -> str:
        records = self.load()
        return body_hash(records[-1]) if records else GENESIS
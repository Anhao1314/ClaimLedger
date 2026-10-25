"""Project-scoped claim store: in-situ capture and budgeted briefs.

Claims are the pipeline's single authority. Sessions and Markdown exports are
evidence and views, never the source. The store is a strict JSONL file that is
fully validated on every read; corruption refuses service instead of guessing.
Deterministic code owns identity, status transitions, conflict surfacing and
byte budgets; semantic judgment stays with the calling agent or human.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ._internal.query_memory import features
from .context import (
    DEFAULT_CONTEXT_BYTES, JsonlEvidenceIndex, build_context, serialize_context, suggest_claim,
)
from .locking import DEFAULT_LOCK_TIMEOUT, FileLock, LockTimeout
from .recovery import _measure, serialize_packet

SCHEMA_VERSION = 1
BACKUP_KIND = "claim-ledger-backup"
AUDIT_KIND = "claim-ledger-audit"
REDACTED_TEXT = "[redacted]"
STATUSES = ("现行", "已过期", "有争议")
STATUS_ALIASES = {"current": "现行", "superseded": "已过期", "disputed": "有争议"}
CLAIM_ID_RE = re.compile(r"clm_[0-9a-f]{16}\Z")
TOPIC_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
ISO_Z_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
MAX_TEXT = 1000
MAX_CONTEXT = 300
DEFAULT_MAX_BYTES = 8192
CONFLICT_MIN_SHARED = 2
CONFLICT_RATIO = 0.6
KEYS = frozenset((
    "claim_id", "text", "status", "topic", "tags",
    "created_at", "updated_at", "superseded_by",
    "source", "quote", "session_hint",
))
OPTIONAL_KEYS = frozenset((
    "redacted_at", "scope", "expires_at",
    "valid_from", "valid_to", "superseded_at", "depends_on", "disputes",
))
DEFAULT_SCOPE = "all"
RESOLVE_OUTCOMES = ("sustain", "withdraw", "supersede")


def _parse_moment(value, label):
    """Parse an ISO-8601 UTC timestamp into an aware datetime or refuse."""
    if not isinstance(value, str) or not ISO_Z_RE.fullmatch(value):
        raise ClaimStoreError(
            f"{label} must be an ISO-8601 UTC timestamp like 2026-12-31T23:59:59Z")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ClaimStoreError(f"{label} is not a real UTC datetime: {value!r}") from exc


def _normalize_id_list(value, label):
    """Normalize a claim_id or a list of them; empty and duplicates are refused."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ClaimStoreError(f"{label} must be a claim_id or a list of claim_ids")
    if not items:
        return []
    if any(not isinstance(item, str) or not CLAIM_ID_RE.fullmatch(item) for item in items):
        raise ClaimStoreError(f"{label} must contain valid claim_ids")
    if len(set(items)) != len(items):
        raise ClaimStoreError(f"{label} must not contain duplicate claim_ids")
    return items


def claim_effective_at(claim, now=None):
    """True when the claim's real-world validity window has opened."""
    valid_from = claim.get("valid_from")
    if not valid_from:
        return True
    try:
        opens = datetime.strptime(valid_from, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return opens <= (now or datetime.now(timezone.utc))


def superseded_moment(claim):
    """The system time a claim left the live view; v1 rows fall back to updated_at."""
    return claim.get("superseded_at") or claim["updated_at"]


def status_at(claim, moment):
    """The claim's status at an instant, reconstructed from stored timestamps.

    ``moment`` is an aware datetime. This is an as-of query on the record axis —
    what the ledger believed at ``moment`` — so a claim counts only once it had
    been recorded (``created_at``), once its validity window had opened
    (``valid_from``) and until one of its closing edges (``valid_to``,
    ``expires_at``, ``superseded_at``). Returns one of the stored statuses, or
    ``None`` when none of that applies. Redaction hides content from every
    view, so callers filter redacted rows before asking.
    """
    created = _parse_moment(claim["created_at"], "created_at")
    if moment < created:
        return None
    if not claim_effective_at(claim, moment):
        return None
    for edge in ("valid_to", "expires_at", "superseded_at"):
        value = claim.get(edge)
        if value and _parse_moment(value, edge) <= moment:
            return "已过期"
    if claim["status"] == "已过期":
        return "已过期" if _parse_moment(superseded_moment(claim), "superseded_at") <= moment else "现行"
    return claim["status"]


def find_unmotivated(rows):
    """Current claims whose hard dependencies no longer stand, with the broken ids.

    A dependency is broken when its target was superseded, time-expired or
    redacted. The flag is derived, never stored: the claim keeps its own status
    and the brief reports it separately instead of letting it pass as settled.
    """
    by_id = {row["claim_id"]: row for row in rows}
    out = []
    for claim in rows:
        if claim["status"] != "现行" or claim.get("redacted_at"):
            continue
        if not claim_effective_at(claim):
            continue
        broken = []
        for target_id in claim.get("depends_on") or ():
            target = by_id.get(target_id)
            if target is None or target["status"] == "已过期" \
                    or target.get("redacted_at") or claim_expired_at(target):
                broken.append(target_id)
        if broken:
            out.append({"claim_id": claim["claim_id"], "text": claim["text"],
                        "broken_dependencies": sorted(broken)})
    return out


class ClaimStoreError(ValueError):
    """The store is missing, corrupt or the requested transition is invalid."""


class ClaimStoreBusy(ClaimStoreError):
    """Another process holds the store write lock past the timeout."""


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_store():
    env = os.environ.get("CLAIM_LEDGER_STORE")
    if env:
        return Path(env).expanduser()
    return Path.cwd() / ".claim-ledger" / "claims.jsonl"


def _validate_claim(claim):
    if not isinstance(claim, dict):
        raise ClaimStoreError("claim must be a JSON object")
    allowed = KEYS | OPTIONAL_KEYS
    if not KEYS <= set(claim) or set(claim) - allowed:
        missing = sorted(KEYS - set(claim))
        extra = sorted(set(claim) - allowed)
        raise ClaimStoreError(f"schema mismatch; missing={missing} unknown={extra}")
    if not isinstance(claim["claim_id"], str) or not CLAIM_ID_RE.fullmatch(claim["claim_id"]):
        raise ClaimStoreError(f"invalid claim_id: {claim['claim_id']!r}")
    if not isinstance(claim["text"], str) or not claim["text"].strip() or len(claim["text"]) > MAX_TEXT:
        raise ClaimStoreError(f"invalid text on {claim['claim_id']}")
    if claim["status"] not in STATUSES:
        raise ClaimStoreError(f"unknown status on {claim['claim_id']}: {claim['status']!r}")
    if not isinstance(claim["topic"], str) or not TOPIC_RE.fullmatch(claim["topic"]):
        raise ClaimStoreError(f"invalid topic on {claim['claim_id']}: {claim['topic']!r}")
    if (not isinstance(claim["tags"], list)
            or any(not isinstance(t, str) or not t or len(t) > 40 for t in claim["tags"])
            or len(set(claim["tags"])) != len(claim["tags"])):
        raise ClaimStoreError(f"invalid tags on {claim['claim_id']}")
    for key in ("created_at", "updated_at"):
        if not isinstance(claim[key], str) or not ISO_Z_RE.fullmatch(claim[key]):
            raise ClaimStoreError(f"invalid {key} on {claim['claim_id']}")
    if claim["superseded_by"] is not None and not CLAIM_ID_RE.fullmatch(str(claim["superseded_by"])):
        raise ClaimStoreError(f"invalid superseded_by on {claim['claim_id']}")
    for key in ("source", "quote", "session_hint"):
        value = claim[key]
        if value is not None and (not isinstance(value, str) or len(value) > MAX_CONTEXT):
            raise ClaimStoreError(f"invalid {key} on {claim['claim_id']}")
    if "redacted_at" in claim:
        redacted_at = claim["redacted_at"]
        if not isinstance(redacted_at, str) or not ISO_Z_RE.fullmatch(redacted_at):
            raise ClaimStoreError(f"invalid redacted_at on {claim['claim_id']}")
        if (claim["text"] != REDACTED_TEXT or claim["tags"]
                or claim["source"] is not None or claim["quote"] is not None
                or claim["session_hint"] is not None):
            raise ClaimStoreError(f"redacted claim still contains content: {claim['claim_id']}")
    if "scope" in claim:
        scope = claim["scope"]
        if not isinstance(scope, str) or not TOPIC_RE.fullmatch(scope):
            raise ClaimStoreError(f"invalid scope on {claim['claim_id']}: {scope!r}")
    if "expires_at" in claim:
        expires_at = claim["expires_at"]
        if expires_at is not None and (
                not isinstance(expires_at, str) or not ISO_Z_RE.fullmatch(expires_at)):
            raise ClaimStoreError(f"invalid expires_at on {claim['claim_id']}")
    for key in ("valid_from", "valid_to"):
        if key in claim:
            value = claim[key]
            if value is not None and (not isinstance(value, str) or not ISO_Z_RE.fullmatch(value)):
                raise ClaimStoreError(f"invalid {key} on {claim['claim_id']}")
    if claim.get("valid_from") and claim.get("valid_to"):
        if _parse_moment(claim["valid_from"], "valid_from") > _parse_moment(claim["valid_to"], "valid_to"):
            raise ClaimStoreError(
                f"valid_from is after valid_to on {claim['claim_id']}")
    if "superseded_at" in claim:
        superseded_at = claim["superseded_at"]
        if superseded_at is not None:
            if not isinstance(superseded_at, str) or not ISO_Z_RE.fullmatch(superseded_at):
                raise ClaimStoreError(f"invalid superseded_at on {claim['claim_id']}")
            if claim["status"] != "已过期":
                raise ClaimStoreError(
                    f"superseded_at set on non-expired claim: {claim['claim_id']}")
    for key in ("depends_on", "disputes"):
        if key in claim:
            value = claim[key]
            if value is None:
                continue
            if not isinstance(value, list):
                raise ClaimStoreError(f"{key} must be a list of claim_ids on {claim['claim_id']}")
            _normalize_id_list(value, key)
            if claim["claim_id"] in value:
                raise ClaimStoreError(f"{key} must not reference itself: {claim['claim_id']}")
    if claim.get("disputes") and claim["status"] != "有争议":
        raise ClaimStoreError(f"disputes set on non-disputed claim: {claim['claim_id']}")


def claim_scope(claim):
    """The environment a claim applies to; rows written before 0.6.0 are 'all'."""
    return claim.get("scope", DEFAULT_SCOPE)


def claim_expired_at(claim, now=None):
    """True when a claim's optional expires_at timestamp has passed.

    Expiry is a read-time policy, never a stored status: the row keeps its
    status and supersession chain, and the brief counts it as time_expired.
    """
    expires_at = claim.get("expires_at")
    if not expires_at:
        return False
    try:
        moment = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    now = now or datetime.now(timezone.utc)
    return moment <= now


def scope_overlaps(candidate, stored):
    """Two claims may conflict only when their scopes can both apply."""
    return candidate == stored or DEFAULT_SCOPE in (candidate, stored)


def _normalize_expires_at(value, now):
    if value is None:
        return None
    if not isinstance(value, str) or not ISO_Z_RE.fullmatch(value):
        raise ClaimStoreError("expires_at must be an ISO-8601 UTC timestamp like 2026-12-31T23:59:59Z")
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ClaimStoreError(f"expires_at is not a real UTC datetime: {value!r}") from exc
    if moment <= now:
        raise ClaimStoreError("expires_at must be in the future; a claim that already expired should not be recorded")
    return value


def _normalize_scope(value):
    if value is None:
        return DEFAULT_SCOPE
    if not isinstance(value, str) or not TOPIC_RE.fullmatch(value):
        raise ClaimStoreError(f"scope must match {TOPIC_RE.pattern!r}: {value!r}")
    return value


def _validate_rows(rows, source):
    """Validate identity and supersession relations for a complete row set."""
    by_id = {}
    for claim in rows:
        if claim["claim_id"] in by_id:
            raise ClaimStoreError(f"{source}: duplicate claim_id: {claim['claim_id']}")
        by_id[claim["claim_id"]] = claim
    for claim in rows:
        target = claim["superseded_by"]
        if claim["status"] == "已过期":
            if target is None:
                raise ClaimStoreError(f"{source}: expired claim without successor: {claim['claim_id']}")
            if target not in by_id:
                raise ClaimStoreError(
                    f"{source}: dangling superseded_by on {claim['claim_id']}: {target}")
        elif target is not None:
            raise ClaimStoreError(
                f"{source}: superseded_by set on non-expired claim: {claim['claim_id']}")
    for claim in rows:
        seen, cursor = set(), claim["claim_id"]
        while cursor is not None:
            if cursor in seen:
                raise ClaimStoreError(
                    f"{source}: supersession cycle reached from {claim['claim_id']}")
            seen.add(cursor)
            cursor = by_id[cursor]["superseded_by"] if cursor in by_id else None
    for claim in rows:
        for key in ("depends_on", "disputes"):
            for target in claim.get(key) or ():
                if target not in by_id:
                    raise ClaimStoreError(
                        f"{source}: dangling {key} reference on {claim['claim_id']}: {target}")


def _serialize_rows(rows):
    return "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for r in rows)


def _write_bytes(path, payload):
    """Write bytes atomically with an fsync before replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".claims-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except OSError as exc:
                if attempt == 4 or getattr(exc, "winerror", None) not in (5, 32):
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _actor():
    value = os.environ.get("CLAIM_LEDGER_ACTOR", "").strip()
    return value[:80] or None


def normalize_status(value):
    """Accept the stored status or its English alias used by the docs and MCP clients."""
    if not isinstance(value, str):
        raise ClaimStoreError("status must be a string")
    normalized = STATUS_ALIASES.get(value.strip().lower(), value)
    if normalized not in STATUSES:
        raise ClaimStoreError(f"unknown status filter: {value!r}")
    return normalized


def _supersede_targets(supersedes):
    """Normalize a single id or an explicit list of ids without losing intent."""
    if supersedes is None:
        return []
    if isinstance(supersedes, str):
        targets = [supersedes]
    elif isinstance(supersedes, (list, tuple, set)):
        targets = sorted(supersedes) if isinstance(supersedes, set) else list(supersedes)
    else:
        raise ClaimStoreError("supersedes must be a claim_id or a list of claim_ids")
    if not targets:
        return []
    if any(not isinstance(target, str) or not CLAIM_ID_RE.fullmatch(target) for target in targets):
        raise ClaimStoreError("supersedes must contain valid claim_ids")
    if len(set(targets)) != len(targets):
        raise ClaimStoreError("supersedes must not contain duplicate claim_ids")
    return targets


def find_conflicts(text, current):
    """Lexical overlap against current claims; a candidate is surfaced, never auto-resolved.

    Deterministic matching cannot see semantic contradictions; a high overlap is
    reported as a possible conflict and the caller must resolve it explicitly.
    """
    query = features(text)
    if len(query) < CONFLICT_MIN_SHARED:
        return []
    out = []
    for claim in current:
        other = features(claim["text"])
        shared = query & other
        if len(shared) >= CONFLICT_MIN_SHARED and len(shared) / min(len(query), len(other)) >= CONFLICT_RATIO:
            out.append(claim)
    return out


class ClaimStore:
    """Single-file claim store with one cross-process writer at a time."""

    def __init__(self, path=None, *, lock_timeout=DEFAULT_LOCK_TIMEOUT):
        if not isinstance(lock_timeout, (int, float)) or lock_timeout < 0:
            raise ClaimStoreError("lock_timeout must be a non-negative number")
        self.path = Path(path or default_store())
        self.lock_timeout = float(lock_timeout)

    @contextlib.contextmanager
    def _locked(self):
        try:
            with FileLock(self.path.with_name(self.path.name + ".lock"),
                          timeout=self.lock_timeout):
                yield
        except LockTimeout as exc:
            raise ClaimStoreBusy(str(exc)) from exc

    def _read(self):
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ClaimStoreError(f"cannot read {self.path}: {exc}") from exc
        return self._parse_rows(text, self.path)

    def _parse_rows(self, text, source):
        rows = []
        for lineno, line in enumerate(text.splitlines(), 1):
            try:
                claim = json.loads(line)
                _validate_claim(claim)
            except (json.JSONDecodeError, ClaimStoreError) as exc:
                raise ClaimStoreError(f"{source} line {lineno}: {exc}") from exc
            rows.append(claim)
        _validate_rows(rows, source)
        return rows

    def _write(self, rows):
        _validate_rows(rows, self.path)
        _write_bytes(self.path, _serialize_rows(rows).encode("utf-8"))

    def digest(self, rows=None):
        """SHA-256 over the canonical serialization; independent of file formatting."""
        if rows is None:
            rows = self._read()
        body = "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for r in rows)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def backup(self, directory=None, *, keep=None):
        """Write a verified snapshot plus manifest; optionally prune older ones."""
        if keep is not None and (type(keep) is not int or keep < 1):
            raise ClaimStoreError("keep must be a positive integer when provided")
        with self._locked():
            if not self.path.exists():
                raise ClaimStoreError(f"claim store not found: {self.path}")
            result = self._backup_locked(self._read(), directory)
        if keep is not None:
            result["pruned"] = self._prune_backups(result, keep)
        return result

    def _prune_backups(self, result, keep):
        """Delete older snapshots beyond ``keep``; the fresh one is never removed."""
        backup_dir = Path(result["path"]).parent
        prefix = f"{self.path.stem}-"
        snapshots = sorted(
            (p for p in backup_dir.glob(prefix + "*.jsonl")
             if not p.name.endswith(".manifest.json")),
            key=lambda p: p.name, reverse=True)
        fresh = Path(result["path"]).resolve()
        pruned = []
        for old in snapshots[keep:]:
            if old.resolve() == fresh:
                continue
            manifest = old.with_name(old.stem + ".manifest.json")
            try:
                old.unlink()
                if manifest.is_file():
                    manifest.unlink()
            except OSError as exc:
                raise ClaimStoreError(f"could not prune backup {old.name}: {exc}") from exc
            pruned.append(old.name)
        return pruned

    def audit_entries(self, *, limit=50, action=None):
        """Return audit entries, newest first; corruption refuses service."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ClaimStoreError("limit must be an integer between 1 and 1000")
        if action is not None and action not in ("redact", "delete", "restore"):
            raise ClaimStoreError("action must be redact, delete or restore")
        path = self._audit_path()
        if not path.is_file():
            return {"ok": True, "path": str(path), "total": 0, "entries": []}
        entries = []
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClaimStoreError(f"{path} line {lineno}: invalid audit entry") from exc
            if not isinstance(entry, dict) or entry.get("kind") != AUDIT_KIND:
                raise ClaimStoreError(f"{path} line {lineno}: not an audit entry")
            entries.append(entry)
        if action is not None:
            entries = [entry for entry in entries if entry.get("action") == action]
        return {"ok": True, "path": str(path), "total": len(entries),
                "entries": list(reversed(entries))[:limit]}

    def backups(self):
        """List snapshots with their manifests, newest first."""
        backup_dir = self._backup_dir()
        out = []
        if backup_dir.is_dir():
            for manifest_path in sorted(backup_dir.glob("*.manifest.json"), reverse=True):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise ClaimStoreError(
                        f"invalid backup manifest {manifest_path.name}: {exc}") from exc
                if not isinstance(manifest, dict) or manifest.get("kind") != BACKUP_KIND:
                    raise ClaimStoreError(
                        f"unknown manifest kind in {manifest_path.name}")
                snapshot = manifest_path.with_name(
                    manifest_path.name[: -len(".manifest.json")] + ".jsonl")
                out.append({
                    "snapshot": snapshot.name,
                    "manifest": manifest_path.name,
                    "present": snapshot.is_file(),
                    "created_at": manifest.get("created_at"),
                    "claims": manifest.get("claims"),
                    "redacted": manifest.get("redacted"),
                    "bytes": manifest.get("bytes"),
                    "file_sha256": manifest.get("file_sha256"),
                    "store_sha256": manifest.get("store_sha256"),
                })
        return {"ok": True, "directory": str(backup_dir), "backups": out}

    def init(self):
        """Create an empty store file; refuse to touch one that already has data."""
        if self.path.is_file() and self.path.stat().st_size > 0:
            raise ClaimStoreError(f"store already exists and is not empty: {self.path}")
        created = not self.path.exists()
        if created:
            _write_bytes(self.path, b"")
        elif not self.path.is_file():
            _write_bytes(self.path, b"")
        absolute = str(self.path.resolve())
        store_flag = f'--store "{absolute}"' if absolute != str(Path(default_store()).resolve()) else ""
        return {
            "ok": True,
            "store": absolute,
            "created": created,
            "next_steps": [
                f'claim record "One-line decision" {store_flag}'.replace("  ", " "),
                f"claim brief {store_flag}".replace("  ", " "),
                f"claim mcp {store_flag}".replace("  ", " "),
                "claim skill install --host claude --scope user",
            ],
        }

    def record(self, text, *, topic="general", tags=None, supersedes=None,
               dispute=False, source=None, quote=None, session_hint=None,
               scope=None, expires_at=None, valid_from=None, valid_to=None,
               depends_on=None):
        """Capture one claim at decision time; conflicts must be resolved explicitly.

        ``scope`` narrows where the claim applies (default ``all``); decisions in
        disjoint scopes can coexist. ``expires_at`` is an optional UTC timestamp:
        past that moment the claim no longer counts as current, without touching
        the stored status or supersession chain. ``valid_from`` / ``valid_to``
        are the real-world validity window (backdating is allowed; a future
        ``valid_from`` schedules the decision). ``depends_on`` lists hard
        dependencies: when one of them stops standing, the brief reports this
        claim as unmotivated instead of settled.
        """
        if not isinstance(text, str) or not text.strip():
            raise ClaimStoreError("claim text must be non-empty")
        text = " ".join(text.split())
        if len(text) > MAX_TEXT:
            raise ClaimStoreError(f"claim text exceeds {MAX_TEXT} characters")
        if not TOPIC_RE.fullmatch(str(topic)):
            raise ClaimStoreError(f"topic must match {TOPIC_RE.pattern!r}: {topic!r}")
        tags = list(tags or [])
        if any(not isinstance(t, str) or not t.strip() for t in tags):
            raise ClaimStoreError("tags must be non-empty strings")
        tags = [t.strip() for t in tags]
        if len(set(tags)) != len(tags):
            raise ClaimStoreError("tags must be unique")
        with self._locked():
            return self._record_locked(
                text, topic=topic, tags=tags, supersedes=supersedes, dispute=dispute,
                source=source, quote=quote, session_hint=session_hint,
                scope=scope, expires_at=expires_at, valid_from=valid_from,
                valid_to=valid_to, depends_on=depends_on)

    def _record_locked(self, text, *, topic, tags, supersedes, dispute,
                       source, quote, session_hint, scope, expires_at,
                       valid_from, valid_to, depends_on):
        scope = _normalize_scope(scope)
        expires_at = _normalize_expires_at(expires_at, datetime.now(timezone.utc))
        if valid_from is not None:
            _parse_moment(valid_from, "valid_from")
        if valid_to is not None:
            _parse_moment(valid_to, "valid_to")
        if valid_from and valid_to and valid_from > valid_to:
            raise ClaimStoreError("valid_from must not be after valid_to")
        depends_on = _normalize_id_list(depends_on, "depends_on")
        rows = self._read()
        by_id = {c["claim_id"]: c for c in rows}
        for target in depends_on:
            if target not in by_id:
                raise ClaimStoreError(f"--depends-on target not found: {target}")
        for claim in rows:
            # The duplicate guard protects the live view only: identical text in a
            # disjoint scope is a different decision, and a time-expired claim no
            # longer applies, so recording it again is the natural renewal path.
            if (claim["text"] == text and not claim.get("redacted_at")
                    and not claim_expired_at(claim)
                    and scope_overlaps(scope, claim_scope(claim))):
                raise ClaimStoreError(
                    f"identical claim already exists: {claim['claim_id']}; supersede it instead of duplicating")
        targets = _supersede_targets(supersedes)
        for target in targets:
            if target not in by_id:
                raise ClaimStoreError(f"--supersedes target not found: {target}")
            if by_id[target].get("redacted_at"):
                raise ClaimStoreError(f"--supersedes target is redacted: {target}")
            if by_id[target]["status"] == "已过期":
                raise ClaimStoreError(f"--supersedes target already superseded: {target}")
        current = [c for c in rows
                   if c["status"] == "现行" and not c.get("redacted_at")
                   and not claim_expired_at(c)
                   and scope_overlaps(scope, claim_scope(c))]
        conflicts = find_conflicts(text, current)
        conflict_ids = {c["claim_id"] for c in conflicts}
        if conflicts and not targets and not dispute:
            ids = ", ".join(c["claim_id"] for c in conflicts)
            raise ClaimStoreError(
                f"possible conflict with current claim(s): {ids}; "
                "pass --supersedes <id> to replace, or --dispute to record as disputed")
        if conflicts and targets and not dispute:
            missing = conflict_ids - set(targets)
            if missing:
                ids = ", ".join(sorted(missing))
                raise ClaimStoreError(
                    f"unresolved conflict with current claim(s): {ids}; "
                    "supersede every detected conflict, or use --dispute")
        status = "有争议" if dispute else "现行"
        # A dispute that resolved detected conflicts records what it objects to,
        # so `resolve` can later close the loop without guessing.
        disputes = sorted(conflict_ids) if dispute else []
        claim_id = "clm_" + uuid.uuid4().hex[:16]
        while claim_id in by_id:
            claim_id = "clm_" + uuid.uuid4().hex[:16]
        now = _utc_now()
        claim = {"claim_id": claim_id, "text": text, "status": status, "topic": topic,
                 "tags": tags, "created_at": now, "updated_at": now,
                 "superseded_by": None, "source": source, "quote": quote,
                 "session_hint": session_hint, "scope": scope,
                 "expires_at": expires_at, "valid_from": valid_from,
                 "valid_to": valid_to}
        if depends_on:
            claim["depends_on"] = depends_on
        if disputes:
            claim["disputes"] = disputes
        _validate_claim(claim)
        for target in targets:
            replaced = by_id[target]
            replaced["status"] = "已过期"
            replaced["superseded_by"] = claim_id
            replaced["superseded_at"] = now
            replaced["updated_at"] = now
        rows.append(claim)
        self._write(rows)
        return {"ok": True, "recorded": claim, "status": status,
                "conflicts_with": [c["claim_id"] for c in conflicts],
                "superseded": targets[0] if targets else None,
                "superseded_claims": targets, "store_sha256": self.digest(rows)}

    def resolve(self, claim_id, *, outcome, text=None, topic=None, tags=None,
                source=None, quote=None, session_hint=None, scope=None):
        """Close a recorded dispute; every outcome leaves the chain consistent.

        ``sustain`` promotes the disputed claim to current and supersedes the
        claims it objected to. ``withdraw`` retracts it in favour of the first
        still-standing target. ``supersede`` records a new decision (``text``)
        that replaces both the dispute and its standing targets.
        """
        if outcome not in RESOLVE_OUTCOMES:
            raise ClaimStoreError(f"outcome must be one of {RESOLVE_OUTCOMES}")
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
            raise ClaimStoreError("claim_id must be a valid claim id")
        if outcome == "supersede":
            if not isinstance(text, str) or not text.strip():
                raise ClaimStoreError("supersede resolution requires the new decision text")
            text = " ".join(text.split())
            if len(text) > MAX_TEXT:
                raise ClaimStoreError(f"claim text exceeds {MAX_TEXT} characters")
            if topic is not None and not TOPIC_RE.fullmatch(str(topic)):
                raise ClaimStoreError(f"topic must match {TOPIC_RE.pattern!r}: {topic!r}")
            tags = list(tags or [])
            if len(set(tags)) != len(tags):
                raise ClaimStoreError("tags must be unique")
        with self._locked():
            rows = self._read()
            by_id = {c["claim_id"]: c for c in rows}
            if claim_id not in by_id:
                raise ClaimStoreError(f"claim not found: {claim_id}")
            dispute_claim = by_id[claim_id]
            if dispute_claim["status"] != "有争议":
                raise ClaimStoreError(f"claim is not disputed: {claim_id}")
            if dispute_claim.get("redacted_at"):
                raise ClaimStoreError(f"disputed claim is redacted: {claim_id}")
            targets = dispute_claim.get("disputes") or []
            standing = [t for t in targets
                        if by_id[t]["status"] == "现行" and not by_id[t].get("redacted_at")
                        and not claim_expired_at(by_id[t])]
            superseded_ids = []
            now = _utc_now()

            def retire(row, successor):
                row["status"] = "已过期"
                row["superseded_by"] = successor
                row["superseded_at"] = now
                row["updated_at"] = now
                superseded_ids.append(row["claim_id"])

            if outcome == "withdraw":
                if not standing:
                    raise ClaimStoreError(
                        f"dispute {claim_id} has no standing claim to defer to; "
                        "record the resolution as a new decision instead")
                dispute_claim.pop("disputes", None)
                retire(dispute_claim, standing[0])
            elif outcome == "sustain":
                winner_text = dispute_claim["text"]
                others = [c for c in rows
                          if c["status"] == "现行" and not c.get("redacted_at")
                          and not claim_expired_at(c)
                          and c["claim_id"] != claim_id
                          and c["claim_id"] not in standing]
                leftovers = find_conflicts(winner_text, others)
                if leftovers:
                    ids = ", ".join(c["claim_id"] for c in leftovers)
                    raise ClaimStoreError(
                        f"sustaining {claim_id} would leave unresolved conflicts: {ids}; "
                        "supersede or dispute those first")
                for target in standing:
                    retire(by_id[target], claim_id)
                dispute_claim["status"] = "现行"
                dispute_claim.pop("disputes", None)
                dispute_claim["updated_at"] = now
            else:  # supersede
                others = [c for c in rows
                          if c["status"] == "现行" and not c.get("redacted_at")
                          and not claim_expired_at(c)
                          and c["claim_id"] not in targets]
                leftovers = find_conflicts(text, others)
                if leftovers:
                    ids = ", ".join(c["claim_id"] for c in leftovers)
                    raise ClaimStoreError(
                        f"the new decision conflicts with unrelated current claim(s): {ids}; "
                        "supersede or dispute those first")
                new_id = "clm_" + uuid.uuid4().hex[:16]
                while new_id in by_id:
                    new_id = "clm_" + uuid.uuid4().hex[:16]
                decision = {"claim_id": new_id, "text": text, "status": "现行",
                            "topic": topic or "general", "tags": list(tags or []),
                            "created_at": now, "updated_at": now,
                            "superseded_by": None, "source": source, "quote": quote,
                            "session_hint": session_hint,
                            "scope": _normalize_scope(scope), "expires_at": None}
                _validate_claim(decision)
                for target in standing:
                    retire(by_id[target], new_id)
                dispute_claim.pop("disputes", None)
                retire(dispute_claim, new_id)
                rows.append(decision)
            _validate_rows(rows, self.path)
            self._write(rows)
            promoted = outcome == "sustain"
            return {"ok": True, "action": "resolve", "outcome": outcome,
                    "dispute": claim_id, "resolved": True,
                    "superseded_claims": superseded_ids,
                    "promoted": promoted,
                    "recorded": decision if outcome == "supersede" else None,
                    "store_sha256": self.digest(rows)}

    def claims(self, *, status=None, topic=None, query=None, include_redacted=False,
               scope=None, include_time_expired=True, at=None):
        rows = self._read()
        if not include_redacted:
            rows = [c for c in rows if not c.get("redacted_at")]
        if isinstance(status, str) and status.strip().lower() == "all":
            status = "all"
        if status is not None and status != "all":
            status = normalize_status(status)
            if at is not None:
                moment = _parse_moment(at, "at")
                rows = [c for c in rows if status_at(c, moment) == status]
            else:
                rows = [c for c in rows if c["status"] == status]
        elif at is not None:
            raise ClaimStoreError("--at requires an explicit status, not 'all'")
        if topic is not None:
            rows = [c for c in rows if c["topic"] == topic]
        if scope is not None:
            scope = _normalize_scope(scope)
            rows = [c for c in rows if scope_overlaps(scope, claim_scope(c))]
        if status == "现行" and not include_time_expired and at is None:
            rows = [c for c in rows if not claim_expired_at(c)]
        if query:
            q = features(query)
            rows = [c for c in rows if q & features(c["text"])]
        rows.sort(key=lambda c: (c["topic"], c["created_at"], c["claim_id"]))
        return rows

    def brief(self, *, max_bytes=DEFAULT_MAX_BYTES, topic=None, scope=None, at=None):
        """A deterministic, byte-bounded snapshot: disputes first, then current, then history.

        ``scope`` restricts the packet to claims that apply there (``all``-scoped
        claims always apply). A claim whose ``expires_at`` has passed stops
        counting as current; it is reported in ``counts.time_expired`` instead of
        being rewritten, so the stored chain stays immutable. Claims whose hard
        dependencies no longer stand are reported under ``unmotivated`` instead
        of passing as settled. ``at`` reconstructs the view at a past instant
        from stored timestamps: what was current, disputed and superseded then.
        """
        if type(max_bytes) is not int or not 256 <= max_bytes <= 1_048_576:
            raise ClaimStoreError("max_bytes must be an integer between 256 and 1048576")
        if scope is not None:
            scope = _normalize_scope(scope)
        rows = self._read()
        visible = [c for c in rows if not c.get("redacted_at")]
        if scope is not None:
            visible = [c for c in visible if scope_overlaps(scope, claim_scope(c))]
        if at is None:
            # The live view keeps v1 bucket semantics: an expires_at deadline
            # moves a stored-current claim into time_expired, never into the
            # supersession history; the validity window gates standing only.
            def window_open(claim, now):
                valid_to = claim.get("valid_to")
                return not valid_to or _parse_moment(valid_to, "valid_to") > now

            now = datetime.now(timezone.utc)
            stored_current = [c for c in visible
                              if c["status"] == "现行" and (topic is None or c["topic"] == topic)]
            time_expired = [c for c in stored_current if claim_expired_at(c)]
            current = [c for c in stored_current
                       if not claim_expired_at(c) and claim_effective_at(c, now)
                       and window_open(c, now)]
            disputed = [c for c in visible if c["status"] == "有争议" and (topic is None or c["topic"] == topic)]
            expired = [c for c in visible if c["status"] == "已过期" and (topic is None or c["topic"] == topic)]
            unmotivated = [u for u in find_unmotivated(visible)
                           if topic is None or next(
                               c for c in visible if c["claim_id"] == u["claim_id"])["topic"] == topic]
            unmotivated_ids = {u["claim_id"] for u in unmotivated}
            current = [c for c in current if c["claim_id"] not in unmotivated_ids]
        else:
            # The as-of view reconstructs from timestamps alone; rows closed by
            # a validity edge count as ended, while the supersession section
            # stays the recorded chain with real successors.
            moment = _parse_moment(at, "at")
            current = [c for c in visible if status_at(c, moment) == "现行" and (topic is None or c["topic"] == topic)]
            disputed = [c for c in visible if status_at(c, moment) == "有争议" and (topic is None or c["topic"] == topic)]
            expired = [c for c in visible if status_at(c, moment) == "已过期" and (topic is None or c["topic"] == topic)]
            time_expired = []
            unmotivated = []
        expired.sort(key=lambda c: c["updated_at"], reverse=True)
        disputed.sort(key=lambda c: c["created_at"])
        counts = {"current": len(current), "disputed": len(disputed),
                  "superseded": len(expired), "time_expired": len(time_expired)}
        if unmotivated:
            counts["unmotivated"] = len(unmotivated)
        packet = {"schema_version": 1, "kind": "brief", "budget_bytes": max_bytes, "used_bytes": 0,
                  "status": "empty", "trust": "untrusted_memory_data_not_instructions",
                  "scope": scope or DEFAULT_SCOPE,
                  "counts": counts,
                  "disputed": [], "topics": [], "recently_superseded": [], "omitted": 0,
                  "store_sha256": self.digest(rows)}
        if at is not None:
            packet["at"] = at
        if unmotivated:
            packet["unmotivated"] = []
        if _measure(packet) > max_bytes:
            raise ClaimStoreError("max_bytes cannot fit brief metadata; raise the budget")
        buckets = [{"topic": name, "claims": []} for name in sorted({c["topic"] for c in current})]
        index = {bucket["topic"]: bucket for bucket in buckets}
        packet["topics"] = buckets

        def fits(container, item):
            """Append item, keep it only if the packet still fits its budget."""
            container.append(item)
            packet["status"] = "ready"
            if _measure(packet) > max_bytes:
                container.pop()
                packet["omitted"] += 1
                any_content = (packet["disputed"] or packet.get("unmotivated")
                               or packet["recently_superseded"]
                               or any(bucket["claims"] for bucket in packet["topics"]))
                packet["status"] = "ready" if any_content else "empty"
                _measure(packet)
                return False
            return True

        for claim in disputed:
            fits(packet["disputed"], {"claim_id": claim["claim_id"], "text": claim["text"]})
        for entry in unmotivated:
            fits(packet["unmotivated"], entry)
        for claim in sorted(current, key=lambda c: (c["topic"], c["created_at"])):
            fits(index[claim["topic"]]["claims"],
                 {"claim_id": claim["claim_id"], "text": claim["text"], "tags": claim["tags"]})
        for claim in expired[:20]:
            fits(packet["recently_superseded"],
                 {"claim_id": claim["claim_id"], "text": claim["text"],
                  "superseded_by": claim["superseded_by"]})
        packet["topics"] = [b for b in packet["topics"] if b["claims"]]
        any_content = bool(packet["disputed"] or packet.get("unmotivated")
                           or packet["recently_superseded"] or packet["topics"])
        if not any_content:
            packet["status"] = "budget_exhausted" if visible else "empty"
        _measure(packet)
        return packet

    def _backup_dir(self, directory=None):
        return Path(directory) if directory is not None else self.path.parent / "backups"

    def _backup_locked(self, rows, directory=None):
        backup_dir = self._backup_dir(directory)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        base = f"{self.path.stem}-{stamp}"
        target = backup_dir / f"{base}.jsonl"
        counter = 1
        while target.exists():
            target = backup_dir / f"{base}-{counter}.jsonl"
            counter += 1
        body = _serialize_rows(rows).encode("utf-8")
        _write_bytes(target, body)
        manifest = {
            "schema_version": 1,
            "kind": BACKUP_KIND,
            "created_at": _utc_now(),
            "source_name": self.path.name,
            "claims": len(rows),
            "redacted": sum(1 for row in rows if row.get("redacted_at")),
            "bytes": len(body),
            "file_sha256": hashlib.sha256(body).hexdigest(),
            "store_sha256": self.digest(rows),
        }
        manifest_path = backup_dir / f"{base}.manifest.json"
        _write_bytes(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        return {"ok": True, "path": str(target), "manifest": str(manifest_path),
                "claims": len(rows), "bytes": len(body),
                "file_sha256": manifest["file_sha256"], "store_sha256": manifest["store_sha256"]}

    def _chain_ids(self, rows, claim_id):
        adjacency = {}
        for row in rows:
            adjacency.setdefault(row["claim_id"], set())
            target = row["superseded_by"]
            if target is not None:
                adjacency.setdefault(target, set())
                adjacency[row["claim_id"]].add(target)
                adjacency[target].add(row["claim_id"])
        seen = set()
        stack = [claim_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, ()))
        return sorted(seen)

    def _audit_path(self):
        return self.path.with_name(self.path.stem + ".audit.jsonl")

    def _append_audit(self, action, claim_ids, before_digest, after_digest, backup):
        entry = {
            "schema_version": 1,
            "kind": AUDIT_KIND,
            "action": action,
            "claim_ids": list(claim_ids),
            "at": _utc_now(),
            "actor": _actor(),
            "store_sha256_before": before_digest,
            "store_sha256_after": after_digest,
            "backup_file": Path(backup["path"]).name if backup else None,
            "backup_file_sha256": backup["file_sha256"] if backup else None,
        }
        path = self._audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return str(path)

    def _finish_mutation(self, action, rows_before, rows_after, claim_ids,
                         before_digest, backup, *, previous_exists=True):
        self._write(rows_after)
        after_digest = self.digest(rows_after)
        try:
            audit = self._append_audit(action, claim_ids, before_digest, after_digest, backup)
        except OSError as exc:
            if previous_exists:
                self._write(rows_before)
            elif self.path.exists():
                self.path.unlink()
            raise ClaimStoreError(
                f"{action} rolled back: could not write audit log: {exc}") from exc
        return audit, after_digest

    def redact(self, claim_id, *, cascade=False, keep_backup=True, backup_dir=None):
        """Remove claim content in place while preserving identity and chain shape.

        A backup is written first unless ``keep_backup`` is False, then the store
        and an audit entry. Redacted rows are excluded from briefs, listings and
        evidence resolution by default; the topic is replaced too, since it may be
        sensitive. Derived evidence indexes must be rebuilt or purged separately.
        """
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
            raise ClaimStoreError("claim_id must be a valid claim id")
        with self._locked():
            rows = self._read()
            by_id = {row["claim_id"]: row for row in rows}
            if claim_id not in by_id:
                raise ClaimStoreError(f"claim not found: {claim_id}")
            if by_id[claim_id].get("redacted_at"):
                return {"ok": True, "action": "redact", "claim_ids": [claim_id],
                        "already_redacted": True, "store_sha256": self.digest(rows)}
            targets = self._chain_ids(rows, claim_id) if cascade else [claim_id]
            targets = [target for target in targets
                       if not by_id[target].get("redacted_at")]
            if not targets:
                return {"ok": True, "action": "redact", "claim_ids": [claim_id],
                        "already_redacted": True, "store_sha256": self.digest(rows)}
            rows_before = [dict(row) for row in rows]
            before_digest = self.digest(rows)
            backup = self._backup_locked(rows, backup_dir) if keep_backup else None
            now = _utc_now()
            for target in targets:
                row = by_id[target]
                row["text"] = REDACTED_TEXT
                row["tags"] = []
                row["topic"] = "redacted"
                row["source"] = None
                row["quote"] = None
                row["session_hint"] = None
                row["redacted_at"] = now
                row["updated_at"] = now
            audit, after_digest = self._finish_mutation(
                "redact", rows_before, rows, targets, before_digest, backup)
            return {"ok": True, "action": "redact", "claim_ids": targets,
                    "already_redacted": False, "backup": backup, "audit": audit,
                    "store_sha256": after_digest}

    def delete(self, claim_id, *, cascade=False, keep_backup=True, backup_dir=None):
        """Permanently remove one claim, or its whole supersession chain with cascade."""
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
            raise ClaimStoreError("claim_id must be a valid claim id")
        with self._locked():
            rows = self._read()
            by_id = {row["claim_id"]: row for row in rows}
            if claim_id not in by_id:
                raise ClaimStoreError(f"claim not found: {claim_id}")
            referenced_by = sorted(
                row["claim_id"] for row in rows if row["superseded_by"] == claim_id)
            if referenced_by and not cascade:
                raise ClaimStoreError(
                    f"claim {claim_id} is referenced by {', '.join(referenced_by)}; "
                    "use --cascade to delete the whole supersession chain")
            remove_ids = set(self._chain_ids(rows, claim_id)) if cascade else {claim_id}
            remaining = [row for row in rows if row["claim_id"] not in remove_ids]
            _validate_rows(remaining, self.path)
            rows_before = [dict(row) for row in rows]
            before_digest = self.digest(rows)
            backup = self._backup_locked(rows, backup_dir) if keep_backup else None
            audit, after_digest = self._finish_mutation(
                "delete", rows_before, remaining, sorted(remove_ids),
                before_digest, backup)
            return {"ok": True, "action": "delete", "claim_ids": sorted(remove_ids),
                    "backup": backup, "audit": audit, "store_sha256": after_digest}

    def restore(self, backup_path, *, overwrite=False, allow_unverified=False,
                backup_dir=None):
        """Verify and atomically restore a backup snapshot, preserving the current store."""
        backup_path = Path(backup_path)
        if not backup_path.is_file():
            raise ClaimStoreError(f"backup not found: {backup_path}")
        raw = backup_path.read_bytes()
        manifest_path = backup_path.with_name(backup_path.stem + ".manifest.json")
        manifest = None
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ClaimStoreError(f"invalid backup manifest: {exc}") from exc
            if not isinstance(manifest, dict) or manifest.get("kind") != BACKUP_KIND:
                raise ClaimStoreError("backup manifest has an unknown kind")
            if manifest.get("bytes") != len(raw):
                raise ClaimStoreError("backup byte count does not match its manifest")
            if manifest.get("file_sha256") != hashlib.sha256(raw).hexdigest():
                raise ClaimStoreError("backup file digest does not match its manifest")
        elif not allow_unverified:
            raise ClaimStoreError(
                "backup manifest is missing; pass --allow-unverified to restore raw JSONL")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ClaimStoreError(f"backup is not UTF-8: {exc}") from exc
        rows = self._parse_rows(text, backup_path)
        store_digest = self.digest(rows)
        if manifest is not None:
            if manifest.get("store_sha256") != store_digest:
                raise ClaimStoreError("backup store digest does not match its manifest")
            if manifest.get("claims") != len(rows):
                raise ClaimStoreError("backup claim count does not match its manifest")
        with self._locked():
            previous_exists = self.path.exists()
            current_rows = self._read()
            if previous_exists and current_rows and not overwrite:
                raise ClaimStoreError(
                    "destination store is not empty; pass overwrite to replace it")
            before_digest = self.digest(current_rows)
            previous_backup = (
                self._backup_locked(current_rows, backup_dir)
                if previous_exists and current_rows else None)
            audit, after_digest = self._finish_mutation(
                "restore", current_rows, rows, [], before_digest,
                previous_backup, previous_exists=previous_exists)
            return {"ok": True, "action": "restore", "restored": str(backup_path),
                    "claims": len(rows), "backup_of_previous": previous_backup,
                    "audit": audit, "store_sha256": after_digest}

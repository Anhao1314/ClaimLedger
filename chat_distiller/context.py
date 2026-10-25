"""Composite context: a deterministic claim brief plus optional RAG evidence.

RAG is an evidence layer here, not an authority. Every evidence hit must resolve
to a claim in the store, and the same status policy that governs briefs governs
evidence: a superseded claim never enters a ``current`` packet, and is labelled
historical in a ``historical`` packet. The JSONL claim store remains the only
authority; an evidence index is a derived, rebuildable view.

The built-in :class:`JsonlEvidenceIndex` is a small lexical reference adapter so
the packet can be exercised without dependencies. A host may supply any object
with ``search(query, top_k=...)`` returning :class:`EvidenceHit` values (a local
vector store, BM25 service, or the host's own retriever).
"""
from __future__ import annotations

import hashlib
import json
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from ._internal.query_memory import features

SCHEMA_VERSION = 1
from .status import STATUS_CURRENT, STATUS_DISPUTED, STATUS_SUPERSEDED

STATUS_LABELS = {STATUS_CURRENT: "current", STATUS_SUPERSEDED: "superseded", STATUS_DISPUTED: "disputed"}
DEFAULT_CONTEXT_BYTES = 4096
MIN_CONTEXT_BYTES = 2048
MAX_CONTEXT_BYTES = 1_048_576
DEFAULT_TOP_K = 8
DEFAULT_MAX_PER_CLAIM = 2
DEFAULT_RETRIEVER_TIMEOUT = 5.0


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in value)


def _rows_blob(rows):
    return "".join(
        json.dumps({
            "id": row["chunk_id"],
            "text": row["text"],
            "claim_id": row["claim_id"],
            "source": row["source"],
            "quote": row["quote"],
            "tags": row["tags"],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows)


def _rows_sha256(rows):
    return hashlib.sha256(_rows_blob(rows).encode("utf-8")).hexdigest()


class ContextError(ValueError):
    """The context request, evidence index, or byte budget is invalid."""


class RetrieverTimeout(ContextError):
    """A host evidence retriever exceeded its bounded call time."""


@dataclass(frozen=True)
class EvidenceHit:
    """One retrievable source passage, optionally linked to a claim."""

    text: str
    claim_id: Optional[str] = None
    source: Optional[str] = None
    quote: Optional[str] = None
    score: float = 0.0
    chunk_id: Optional[str] = None


class EvidenceRetriever(Protocol):
    """The seam for a host-owned RAG/vector/BM25 retriever."""

    def search(self, query: str, *, top_k: int = DEFAULT_TOP_K) -> List[EvidenceHit]:
        ...


@dataclass
class EvidenceSelection:
    hits: List[Dict[str, Any]] = field(default_factory=list)
    candidates: int = 0
    stale_excluded: int = 0
    unlinked_excluded: int = 0
    unresolved_excluded: int = 0
    per_claim_omitted: int = 0
    candidate_window: int = 0
    attempts: int = 0


class JsonlEvidenceIndex:
    """Reference evidence adapter over a JSONL chunk file.

    Each line is an object with ``text`` (required) and optional ``id``/``chunk_id``,
    ``claim_id``, ``source``, ``quote`` and ``tags``. Retrieval is lexical and
    deterministic; replacing it with a vector retriever does not change the
    status rules in :class:`StatusAwareRetriever`.
    """

    name = "jsonl-evidence-index"

    def __init__(self, path):
        self.path = Path(path).expanduser()
        if not self.path.is_file():
            raise ContextError(f"evidence index not found: {self.path}")
        rows = []
        self.header = {}
        try:
            raw_bytes = self.path.read_bytes()
            lines = raw_bytes.decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ContextError(f"cannot read evidence index: {exc}") from exc
        self.index_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        first_content = True
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContextError(f"{self.path} line {lineno}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ContextError(f"{self.path} line {lineno}: expected a JSON object")
            if first_content and row.get("kind") == "evidence-index":
                if row.get("schema_version") != 1:
                    raise ContextError(f"{self.path} line {lineno}: unsupported index schema_version")
                declared = row.get("store_sha256")
                if declared is not None and not _is_sha256(declared):
                    raise ContextError(f"{self.path} line {lineno}: invalid store_sha256")
                rows_sha = row.get("rows_sha256")
                if rows_sha is not None and not _is_sha256(rows_sha):
                    raise ContextError(f"{self.path} line {lineno}: invalid rows_sha256")
                self.header = row
                first_content = False
                continue
            first_content = False
            text = row.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ContextError(f"{self.path} line {lineno}: text must be non-empty")
            chunk_id = row.get("id") or row.get("chunk_id")
            if chunk_id is not None and not isinstance(chunk_id, str):
                raise ContextError(f"{self.path} line {lineno}: id must be a string")
            claim_id = row.get("claim_id")
            if claim_id is not None and not isinstance(claim_id, str):
                raise ContextError(f"{self.path} line {lineno}: claim_id must be a string")
            tags = row.get("tags") or []
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                raise ContextError(f"{self.path} line {lineno}: tags must be strings")
            for key in ("source", "quote"):
                if row.get(key) is not None and not isinstance(row.get(key), str):
                    raise ContextError(f"{self.path} line {lineno}: {key} must be a string")
            rows.append({
                "chunk_id": chunk_id or f"ev_{lineno:04d}",
                "text": text,
                "claim_id": claim_id,
                "source": row.get("source"),
                "quote": row.get("quote"),
                "tags": tags,
            })
        self.rows = rows
        self.store_sha256 = self.header.get("store_sha256")
        declared_rows = self.header.get("rows_sha256")
        if declared_rows is not None and declared_rows != _rows_sha256(rows):
            raise ContextError(f"{self.path}: sealed rows digest does not match the header")
        declared_chunks = self.header.get("chunks")
        if declared_chunks is not None and declared_chunks != len(rows):
            raise ContextError(f"{self.path}: sealed chunk count does not match the header")

    def status(self, store_sha256=None):
        """Report whether this index is sealed and still matches a claim store."""
        declared = self.store_sha256
        matches = None
        if declared is not None and store_sha256 is not None:
            matches = declared == store_sha256
        return {
            "ok": matches is not False,
            "path": str(self.path),
            "sealed": declared is not None,
            "chunks": len(self.rows),
            "index_sha256": self.index_sha256,
            "declared_store_sha256": declared,
            "store_matches": matches,
            "rows_sha256": self.header.get("rows_sha256"),
        }

    def seal(self, destination, store_sha256):
        """Write a sealed copy that binds the chunks to one claim-store digest."""
        if not _is_sha256(store_sha256):
            raise ContextError("store_sha256 must be a 64-character hex digest")
        destination = Path(destination).expanduser()
        if destination.exists() or destination.is_symlink():
            raise ContextError(f"sealed index destination already exists: {destination}")
        rows_blob = _rows_blob(self.rows)
        header = {
            "schema_version": 1,
            "kind": "evidence-index",
            "store_sha256": store_sha256,
            "chunks": len(self.rows),
            "rows_sha256": hashlib.sha256(rows_blob.encode("utf-8")).hexdigest(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.write(rows_blob)
        sealed = JsonlEvidenceIndex(destination)
        result = sealed.status(store_sha256)
        result["source"] = str(self.path)
        return result

    def search(self, query, *, top_k=DEFAULT_TOP_K):
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ContextError("top_k must be an integer between 1 and 100")
        q = features(query)
        if not q:
            return []
        scored = []
        for row in self.rows:
            haystack = " ".join([
                row["text"], row["source"] or "", row["quote"] or "", " ".join(row["tags"]),
            ])
            f = features(haystack)
            shared = q & f
            if not shared:
                continue
            score = len(shared) / (len(f) ** 0.5)
            scored.append((round(score, 6), row))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [
            EvidenceHit(
                text=row["text"], claim_id=row["claim_id"], source=row["source"],
                quote=row["quote"], score=score, chunk_id=row["chunk_id"])
            for score, row in scored[:top_k]
        ]


class StatusAwareRetriever:
    """Apply claim identity, status policy, quota and time bounds to evidence."""

    def __init__(self, store, retriever, *, max_per_claim=DEFAULT_MAX_PER_CLAIM,
                 timeout=DEFAULT_RETRIEVER_TIMEOUT):
        if type(max_per_claim) is not int or max_per_claim < 1:
            raise ContextError("max_per_claim must be a positive integer")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
            raise ContextError("timeout must be a positive number of seconds or None")
        self.store = store
        self.retriever = retriever
        self.max_per_claim = max_per_claim
        self.timeout = timeout

    def _raw_search(self, query, window):
        try:
            return self.retriever.search(query, top_k=window)
        except TypeError:
            # A duck-typed retriever may accept positional top_k only.
            return self.retriever.search(query, window)

    def _search(self, query, window):
        if self.timeout is None:
            return self._raw_search(query, window)
        result = queue.Queue()

        def run():
            try:
                result.put(("ok", self._raw_search(query, window)))
            except Exception as exc:  # delivered to the caller thread below
                result.put(("error", exc))

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            kind, value = result.get(timeout=self.timeout)
        except queue.Empty:
            raise RetrieverTimeout(
                f"evidence retriever did not respond within {self.timeout} seconds") from None
        if kind == "error":
            raise value
        return value

    def _select_once(self, raw_hits, *, top_k, intent, by_id):
        if not isinstance(raw_hits, (list, tuple)):
            raise ContextError("retriever.search must return a list of EvidenceHit")
        selection = EvidenceSelection(candidates=len(raw_hits))
        seen = set()
        claim_counts = {}
        for raw in raw_hits:
            if isinstance(raw, dict):
                raw = EvidenceHit(**raw)
            if not isinstance(raw, EvidenceHit):
                raise ContextError("retriever.search returned a non-EvidenceHit item")
            claim_id = raw.claim_id
            if not claim_id:
                selection.unlinked_excluded += 1
                continue
            claim = by_id.get(claim_id)
            if claim is None:
                selection.unresolved_excluded += 1
                continue
            if claim["status"] == STATUS_SUPERSEDED and intent == "current":
                selection.stale_excluded += 1
                continue
            if claim_counts.get(claim_id, 0) >= self.max_per_claim:
                selection.per_claim_omitted += 1
                continue
            key = (claim_id, raw.chunk_id or raw.quote or raw.text[:80])
            if key in seen:
                continue
            seen.add(key)
            claim_counts[claim_id] = claim_counts.get(claim_id, 0) + 1
            excerpt = raw.quote if raw.quote else raw.text[:400]
            selection.hits.append({
                "chunk_id": raw.chunk_id,
                "claim_id": claim_id,
                "claim_text": claim["text"],
                "claim_status": claim["status"],
                "status_label": STATUS_LABELS[claim["status"]],
                "topic": claim["topic"],
                "source": raw.source or claim["source"],
                "quote": raw.quote,
                "excerpt": excerpt,
                "excerpt_truncated": raw.quote is None and len(raw.text) > 400,
                "score": round(float(raw.score), 6),
                "historical": claim["status"] == STATUS_SUPERSEDED,
                "disputed": claim["status"] == STATUS_DISPUTED,
            })
            if len(selection.hits) >= top_k:
                break
        return selection

    def retrieve(self, query, *, top_k=DEFAULT_TOP_K, intent="current"):
        if intent not in ("current", "historical"):
            raise ContextError("intent must be 'current' or 'historical'")
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ContextError("top_k must be an integer between 1 and 100")
        by_id = {row["claim_id"]: row for row in self.store.claims(status="all")}
        window = min(100, max(top_k, top_k * 3))
        selection = self._select_once(
            self._search(query, window), top_k=top_k, intent=intent, by_id=by_id)
        selection.candidate_window = window
        selection.attempts = 1
        attempts = 1
        # If status/identity/quota filters consumed the window, widen instead of
        # returning a starvation result. Stop when the adapter cannot produce more.
        while (len(selection.hits) < top_k and window < 100 and
               (selection.stale_excluded or selection.unlinked_excluded or
                selection.unresolved_excluded or selection.per_claim_omitted)):
            previous_candidates = selection.candidates
            previous_hits = len(selection.hits)
            next_window = min(100, window * 2)
            if next_window <= window:
                break
            window = next_window
            selection = self._select_once(
                self._search(query, window), top_k=top_k, intent=intent, by_id=by_id)
            selection.candidate_window = window
            attempts += 1
            selection.attempts = attempts
            if selection.candidates <= previous_candidates and len(selection.hits) <= previous_hits:
                break
        return selection


def serialize_context(packet):
    """Canonical wire representation; the byte budget includes the final newline."""
    return json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False) + "\n"


def _measure(packet):
    for _ in range(20):
        size = len(serialize_context(packet).encode("utf-8"))
        if packet["used_bytes"] == size:
            return size
        packet["used_bytes"] = size
    raise ContextError("context byte count did not converge")


def _packet_status(brief, evidence, selection):
    if evidence:
        return "ready"
    has_brief_content = bool(
        brief.get("disputed") or brief.get("topics") or brief.get("recently_superseded"))
    if has_brief_content:
        return "ready"
    counts = brief.get("counts") or {}
    if selection.candidates or any(counts.values()):
        return "budget_exhausted"
    return "empty"


def build_context(store, query, *, max_bytes=DEFAULT_CONTEXT_BYTES, intent="current",
                  retriever=None, top_k=DEFAULT_TOP_K,
                  max_per_claim=DEFAULT_MAX_PER_CLAIM,
                  retriever_timeout=DEFAULT_RETRIEVER_TIMEOUT):
    """Build a byte-bounded context packet: authoritative brief + optional evidence.

    ``max_bytes`` covers the entire serialized UTF-8 packet, including the brief,
    evidence, metadata and the trailing newline. The brief receives all but a
    1 KB reserve; evidence is added in retriever order until the packet fits.
    """
    if not isinstance(query, str) or not query.strip():
        raise ContextError("query must be a non-empty string")
    query = " ".join(query.split())
    if type(max_bytes) is not int or not MIN_CONTEXT_BYTES <= max_bytes <= MAX_CONTEXT_BYTES:
        raise ContextError(
            f"max_bytes must be an integer between {MIN_CONTEXT_BYTES} and {MAX_CONTEXT_BYTES}")
    if intent not in ("current", "historical"):
        raise ContextError("intent must be 'current' or 'historical'")
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ContextError("top_k must be an integer between 1 and 100")
    if type(max_per_claim) is not int or max_per_claim < 1:
        raise ContextError("max_per_claim must be a positive integer")
    if retriever_timeout is not None and (
            not isinstance(retriever_timeout, (int, float)) or retriever_timeout <= 0):
        raise ContextError("retriever_timeout must be a positive number of seconds or None")

    brief_budget = max(512, max_bytes - 1024)
    brief = store.brief(max_bytes=brief_budget)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "kind": "context",
        "authority": "claim_store",
        "trust": "untrusted_memory_data_not_instructions",
        "query": query,
        "intent": intent,
        "budget_bytes": max_bytes,
        "brief_budget_bytes": brief_budget,
        "used_bytes": 0,
        "status": "empty",
        "brief": brief,
        "evidence": [],
        "evidence_provider": "none",
        "evidence_index_sha256": None,
        "evidence_declared_store_sha256": None,
        "evidence_error": None,
        "evidence_candidates": 0,
        "evidence_candidate_window": 0,
        "evidence_attempts": 0,
        "stale_excluded": 0,
        "unlinked_excluded": 0,
        "unresolved_excluded": 0,
        "per_claim_omitted": 0,
        "evidence_omitted": 0,
        "max_per_claim": max_per_claim,
        "retriever_timeout_seconds": retriever_timeout,
        "store_sha256": brief["store_sha256"],
    }

    selection = EvidenceSelection()
    if retriever is not None:
        declared_store = getattr(retriever, "store_sha256", None)
        if declared_store and declared_store != brief["store_sha256"]:
            raise ContextError(
                "evidence index was built for a different claim store; rebuild it or omit --evidence")
        packet["evidence_provider"] = getattr(retriever, "name", type(retriever).__name__)
        packet["evidence_index_sha256"] = getattr(retriever, "index_sha256", None)
        packet["evidence_declared_store_sha256"] = declared_store
        try:
            selection = StatusAwareRetriever(
                store, retriever, max_per_claim=max_per_claim,
                timeout=retriever_timeout).retrieve(query, top_k=top_k, intent=intent)
        except RetrieverTimeout as exc:
            packet["evidence_error"] = "timeout: " + str(exc)
        except Exception as exc:  # the brief must remain usable if an adapter fails
            packet["evidence_error"] = type(exc).__name__ + ": " + str(exc)
    packet["evidence_candidates"] = selection.candidates
    packet["evidence_candidate_window"] = selection.candidate_window
    packet["evidence_attempts"] = selection.attempts
    packet["stale_excluded"] = selection.stale_excluded
    packet["unlinked_excluded"] = selection.unlinked_excluded
    packet["unresolved_excluded"] = selection.unresolved_excluded
    packet["per_claim_omitted"] = selection.per_claim_omitted

    if _measure(packet) > max_bytes:
        raise ContextError("max_bytes cannot fit context metadata and the brief")

    included = 0
    for item in selection.hits:
        packet["evidence"].append(item)
        if _measure(packet) > max_bytes:
            packet["evidence"].pop()
            break
        included += 1
    packet["evidence_omitted"] = len(selection.hits) - included
    packet["status"] = _packet_status(brief, packet["evidence"], selection)
    _measure(packet)
    return packet


def suggest_claim(store, text, *, topic="general", tags=None, query=None,
                  retriever=None, top_k=DEFAULT_TOP_K,
                  max_per_claim=DEFAULT_MAX_PER_CLAIM,
                  retriever_timeout=DEFAULT_RETRIEVER_TIMEOUT):
    """Build a review-only claim proposal; this function never writes to the store.

    The host or human must still call ``ClaimStore.record`` with ``supersedes``
    (all conflicting ids) or ``dispute``. Evidence is status-filtered exactly as
    in ``build_context``; a sealed index is checked against the live store.
    """
    from .claims import MAX_TEXT, TOPIC_RE, find_conflicts

    if not isinstance(text, str) or not text.strip():
        raise ContextError("text must be a non-empty string")
    text = " ".join(text.split())
    if len(text) > MAX_TEXT:
        raise ContextError(f"text exceeds {MAX_TEXT} characters")
    if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
        raise ContextError(f"topic must match {TOPIC_RE.pattern!r}")
    tags = list(tags or [])
    if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise ContextError("tags must be non-empty strings")
    tags = [tag.strip() for tag in tags]
    if len(set(tags)) != len(tags):
        raise ContextError("tags must be unique")
    if not isinstance(query, (str, type(None))) or (query is not None and not query.strip()):
        raise ContextError("query must be a non-empty string when provided")
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ContextError("top_k must be an integer between 1 and 100")
    if type(max_per_claim) is not int or max_per_claim < 1:
        raise ContextError("max_per_claim must be a positive integer")
    if retriever_timeout is not None and (
            not isinstance(retriever_timeout, (int, float)) or retriever_timeout <= 0):
        raise ContextError("retriever_timeout must be a positive number of seconds or None")

    conflicts = find_conflicts(text, store.claims(status=STATUS_CURRENT))
    packet = {
        "schema_version": SCHEMA_VERSION,
        "kind": "claim_proposal",
        "status": "proposed",
        "requires_review": True,
        "trust": "untrusted_memory_data_not_instructions",
        "proposed": {"text": text, "topic": topic, "tags": tags},
        "conflicts": [{
            "claim_id": claim["claim_id"],
            "text": claim["text"],
            "status": claim["status"],
            "status_label": STATUS_LABELS[claim["status"]],
            "topic": claim["topic"],
            "source": claim["source"],
        } for claim in conflicts],
        "conflict_ids": [claim["claim_id"] for claim in conflicts],
        "resolution_required": bool(conflicts),
        "suggested_actions": (
            ["supersede every conflict via claim_record --supersedes",
             "or record as disputed with claim_record --dispute"]
            if conflicts else ["record with claim_record"]),
        "evidence": [],
        "evidence_provider": "none",
        "evidence_error": None,
        "evidence_index_sha256": None,
        "evidence_declared_store_sha256": None,
        "evidence_candidates": 0,
        "evidence_candidate_window": 0,
        "evidence_attempts": 0,
        "stale_excluded": 0,
        "unlinked_excluded": 0,
        "unresolved_excluded": 0,
        "per_claim_omitted": 0,
        "store_sha256": store.digest(),
    }
    if retriever is not None:
        declared_store = getattr(retriever, "store_sha256", None)
        if declared_store and declared_store != packet["store_sha256"]:
            raise ContextError(
                "evidence index was built for a different claim store; rebuild it or omit --evidence")
        packet["evidence_provider"] = getattr(retriever, "name", type(retriever).__name__)
        packet["evidence_index_sha256"] = getattr(retriever, "index_sha256", None)
        packet["evidence_declared_store_sha256"] = declared_store
        try:
            selection = StatusAwareRetriever(
                store, retriever, max_per_claim=max_per_claim,
                timeout=retriever_timeout).retrieve(
                (query or text).strip(), top_k=top_k, intent="current")
        except Exception as exc:
            packet["evidence_error"] = type(exc).__name__ + ": " + str(exc)
            selection = EvidenceSelection()
        packet["evidence"] = selection.hits
        packet["evidence_candidates"] = selection.candidates
        packet["evidence_candidate_window"] = selection.candidate_window
        packet["evidence_attempts"] = selection.attempts
        packet["stale_excluded"] = selection.stale_excluded
        packet["unlinked_excluded"] = selection.unlinked_excluded
        packet["unresolved_excluded"] = selection.unresolved_excluded
        packet["per_claim_omitted"] = selection.per_claim_omitted
    return packet

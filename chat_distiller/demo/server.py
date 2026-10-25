"""Local interactive demo for the claim ledger.

A zero-dependency HTTP server over the real :class:`ClaimStore`. The browser UI
is a view: every record, supersede, brief and search below calls the same code
paths as the CLI and MCP server. By default the demo runs against a disposable
store seeded with a synthetic project, so it never touches personal data.

    claim demo
    python -m chat_distiller.demo
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..claims import (
    ClaimStore, ClaimStoreBusy, ClaimStoreError, DEFAULT_MAX_BYTES, find_conflicts,
    find_unmotivated, status_at, RESOLVE_OUTCOMES,
)
from ..context import ContextError, JsonlEvidenceIndex, build_context, serialize_context, suggest_claim
from ..recovery import serialize_packet
from .._internal.query_memory import features
from . import scenario

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]
# Checkout first, installed package second; both ship the same synthetic index.
EVIDENCE_SOURCES = (
    REPO_ROOT / "examples" / "rag" / "evidence.jsonl",
    Path(__file__).resolve().parent / "evidence.jsonl",
)
MAX_BODY = 512 * 1024
STATUS_CURRENT = "现行"
STATUS_DISPUTED = "有争议"
STATUS_SUPERSEDED = "已过期"


def _read_json_file(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _load_evidence_index():
    """Load the synthetic demo evidence index; None when it is not shipped."""
    for candidate in EVIDENCE_SOURCES:
        if candidate.is_file():
            try:
                return JsonlEvidenceIndex(candidate)
            except ContextError:
                return None
    return None


def _parse_at(value):
    """Validate an as-of instant for the point-in-time views."""
    if not isinstance(value, str) or not value:
        raise ClaimStoreError("at must be an ISO-8601 UTC timestamp like 2026-09-30T00:00:00Z")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ClaimStoreError(f"at is not a real UTC datetime: {value!r}") from exc


def _norm_tags(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(t, str) for t in value):
        raise ClaimStoreError("tags must be a list of strings")
    return [t.strip() for t in value if t.strip()]


def _counts(rows):
    return {
        "current": sum(1 for r in rows if r["status"] == STATUS_CURRENT),
        "disputed": sum(1 for r in rows if r["status"] == STATUS_DISPUTED),
        "superseded": sum(1 for r in rows if r["status"] == STATUS_SUPERSEDED),
        "total": len(rows),
    }


def _public_claim(row):
    return {
        "claim_id": row["claim_id"],
        "text": row["text"],
        "status": row["status"],
        "topic": row["topic"],
        "tags": row["tags"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "superseded_by": row["superseded_by"],
        "source": row["source"],
        "quote": row["quote"],
        "session_hint": row["session_hint"],
        "redacted_at": row.get("redacted_at"),
        "scope": row.get("scope", "all"),
        "expires_at": row.get("expires_at"),
        "depends_on": row.get("depends_on") or [],
        "disputes": row.get("disputes") or [],
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
        "superseded_at": row.get("superseded_at"),
    }


def _score_claim(query, claim):
    """Transparent lexical score: text overlap first, topic/tags as a small boost."""
    q = features(query)
    if not q:
        return 0.0, []
    text_hits = q & features(claim["text"])
    side_hits = (q & features(claim["topic"])) | (q & features(" ".join(claim["tags"])))
    score = (len(text_hits) + 0.5 * len(side_hits)) / (len(q) ** 0.5)
    matched = sorted(text_hits | side_hits)
    return round(score, 3), matched


class DemoApp:
    def __init__(self, store_path, *, writable=False, seeded=False, mode="demo"):
        self.store_path = Path(store_path)
        self.writable = writable
        self.seeded = seeded
        self.mode = mode
        self.evidence_index = _load_evidence_index()

    @property
    def store(self):
        return ClaimStore(self.store_path)

    def state(self, at=None):
        rows = self.store.claims(status="all", include_redacted=True)
        topics = sorted({r["topic"] for r in rows})
        claims = [_public_claim(r) for r in rows]
        visible = [r for r in rows if not r.get("redacted_at")]
        payload = {
            "ok": True,
            "version": __version__,
            "scenario": scenario.SCENARIO,
            "seeded": self.seeded,
            "writable": self.writable,
            "mode": self.mode,
            "store": {
                "bytes": self.store_path.stat().st_size if self.store_path.exists() else 0,
                "sha256": self.store.digest(),
                "path_label": "disposable demo store" if self.mode == "demo" else str(self.store_path),
            },
            "counts": _counts(rows),
            "topics": topics,
            "claims": claims,
            "unmotivated": find_unmotivated(visible),
            "examples": scenario.EXAMPLES,
            "rag": {
                "available": self.evidence_index is not None,
                "provider": getattr(self.evidence_index, "name", None),
                "chunks": len(self.evidence_index.rows) if self.evidence_index else 0,
                "sealed": bool(getattr(self.evidence_index, "store_sha256", None)),
                "note": ("synthetic evidence index; every hit is joined to a claim "
                         "and passes the same status policy"),
            },
        }
        if at is not None:
            moment = _parse_at(at)
            for claim, row in zip(claims, rows):
                claim["status_at"] = status_at(row, moment)
            counts_at = {"current": 0, "disputed": 0, "superseded": 0, "not_yet": 0}
            for claim in claims:
                key = claim["status_at"]
                if key is None:
                    counts_at["not_yet"] += 1
                elif key == STATUS_SUPERSEDED:
                    counts_at["superseded"] += 1
                else:
                    counts_at["disputed" if key == STATUS_DISPUTED else "current"] += 1
            payload["at"] = at
            payload["counts_at"] = counts_at
        return payload

    def reset(self):
        if self.mode != "demo":
            raise DemoReadOnly("reset is only available for the disposable demo store")
        if self.store_path.exists():
            self.store_path.unlink()
        scenario.seed(self.store_path)
        self.seeded = True
        return self.state()

    def record(self, payload):
        if not self.writable:
            raise DemoReadOnly("this demo is bound to a read-only ledger; restart with --write to record")
        if not isinstance(payload, dict):
            raise ClaimStoreError("request body must be a JSON object")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ClaimStoreError("claim text must be non-empty")
        text = " ".join(text.split())
        topic = payload.get("topic") or "general"
        if not isinstance(topic, str):
            raise ClaimStoreError("topic must be a string")
        tags = _norm_tags(payload.get("tags"))
        supersedes = payload.get("supersedes") or None
        dispute = bool(payload.get("dispute"))
        source = payload.get("source") or None
        quote = payload.get("quote") or None
        session_hint = payload.get("session_hint") or None
        scope = payload.get("scope") or None

        current = self.store.claims(status=STATUS_CURRENT, include_time_expired=False)
        conflicts = find_conflicts(text, current)
        try:
            result = self.store.record(
                text, topic=topic, tags=tags, supersedes=supersedes, dispute=dispute,
                source=source, quote=quote, session_hint=session_hint,
                scope=scope)
        except ClaimStoreError as exc:
            message = str(exc)
            if "identical claim already exists" in message:
                raise DuplicateClaim(message, conflicts) from exc
            if conflicts and "possible conflict" in message and not supersedes and not dispute:
                raise ConflictClaim(message, conflicts) from exc
            if conflicts and "unresolved conflict" in message:
                raise ConflictClaim(message, conflicts) from exc
            raise
        rows = self.store.claims(status="all")
        return {
            "ok": True,
            "receipt": {
                "claim_id": result["recorded"]["claim_id"],
                "status": result["recorded"]["status"],
                "topic": result["recorded"]["topic"],
                "scope": result["recorded"].get("scope", "all"),
                "superseded": result["superseded"],
                "superseded_claims": result.get("superseded_claims", []),
                "conflicts_with": result["conflicts_with"],
                "store_sha256": result["store_sha256"],
                "created_at": result["recorded"]["created_at"],
            },
            "counts": _counts(rows),
        }

    def resolve(self, payload):
        """`claim resolve` over HTTP: close a recorded dispute."""
        if not self.writable:
            raise DemoReadOnly("this demo is bound to a read-only ledger; restart with --write to resolve")
        if not isinstance(payload, dict):
            raise ClaimStoreError("request body must be a JSON object")
        claim_id = payload.get("claim_id")
        outcome = payload.get("outcome")
        if outcome not in RESOLVE_OUTCOMES:
            raise ClaimStoreError(f"outcome must be one of {RESOLVE_OUTCOMES}")
        text = payload.get("text")
        topic = payload.get("topic") or None
        result = self.store.resolve(
            claim_id, outcome=outcome, text=text, topic=topic, tags=_norm_tags(payload.get("tags")))
        rows = self.store.claims(status="all")
        return {
            "ok": True,
            "receipt": {
                "dispute": result["dispute"],
                "outcome": result["outcome"],
                "superseded_claims": result["superseded_claims"],
                "recorded": result["recorded"],
                "promoted": result["promoted"],
                "store_sha256": result["store_sha256"],
            },
            "counts": _counts(rows),
        }

    def brief(self, max_bytes, at=None):
        packet = self.store.brief(max_bytes=max_bytes, at=at)
        wire = serialize_packet(packet)
        included = {c["claim_id"] for c in packet["disputed"]}
        for bucket in packet["topics"]:
            included.update(c["claim_id"] for c in bucket["claims"])
        included.update(c["claim_id"] for c in packet["recently_superseded"])
        rows = self.store.claims(status="all")
        omitted = [
            {"claim_id": r["claim_id"], "text": r["text"], "status": r["status"], "topic": r["topic"]}
            for r in rows if r["claim_id"] not in included
        ]
        return {
            "ok": True,
            "packet": packet,
            "wire": wire,
            "wire_bytes": len(wire.encode("utf-8")),
            "omitted_claims": omitted,
        }

    def search(self, query, include_superseded=False):
        rows = self.store.claims(status="all")
        q = (query or "").strip()
        if not features(q):
            return {"ok": True, "query": q, "mode": "all" if include_superseded else "current",
                    "results": [], "total": 0, "stale_in_results": 0, "disputed_in_results": 0,
                    "hint": "Enter at least one word or number."}
        scored = []
        for row in rows:
            if row["status"] == STATUS_SUPERSEDED and not include_superseded:
                continue
            score, matched = _score_claim(q, row)
            if score <= 0:
                continue
            scored.append((score, matched, row))
        if include_superseded:
            # Raw transcript behaviour: lexical order, no lifecycle awareness.
            # Stable two-pass sort keeps newest claims first on equal scores.
            scored.sort(key=lambda item: item[2]["created_at"], reverse=True)
            scored.sort(key=lambda item: -item[0])
        else:
            rank = {STATUS_CURRENT: 0, STATUS_DISPUTED: 1}
            scored.sort(key=lambda item: item[2]["created_at"], reverse=True)
            scored.sort(key=lambda item: (rank[item[2]["status"]], -item[0]))
        results = []
        for index, (score, matched, row) in enumerate(scored, 1):
            results.append({
                "rank": index,
                "claim_id": row["claim_id"],
                "text": row["text"],
                "status": row["status"],
                "topic": row["topic"],
                "tags": row["tags"],
                "score": score,
                "matched": matched,
                "source": row["source"],
                "superseded_by": row["superseded_by"],
            })
        return {
            "ok": True,
            "query": q,
            "mode": "all" if include_superseded else "current",
            "results": results,
            "total": len(results),
            "stale_in_results": sum(1 for r in results if r["status"] == STATUS_SUPERSEDED),
            "disputed_in_results": sum(1 for r in results if r["status"] == STATUS_DISPUTED),
        }

    def context(self, query, intent="current", max_bytes=4096, top_k=8,
                max_per_claim=2, timeout=5.0):
        """`claim recall` over HTTP: brief + status-filtered evidence, read-only."""
        packet = build_context(
            self.store, query, max_bytes=max_bytes, intent=intent,
            retriever=self.evidence_index, top_k=top_k,
            max_per_claim=max_per_claim, retriever_timeout=timeout)
        return {"ok": True, "packet": packet, "wire": serialize_context(packet),
                "wire_bytes": len(serialize_context(packet).encode("utf-8")),
                "rag_available": self.evidence_index is not None}

    def suggest(self, payload):
        """`claim suggest` over HTTP: a review-only proposal; never writes."""
        if not isinstance(payload, dict):
            raise ClaimStoreError("request body must be a JSON object")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ClaimStoreError("text must be non-empty")
        topic = payload.get("topic") or "general"
        if not isinstance(topic, str):
            raise ClaimStoreError("topic must be a string")
        tags = _norm_tags(payload.get("tags"))
        query = payload.get("query")
        proposal = suggest_claim(
            self.store, text, topic=topic, tags=tags, query=query,
            retriever=self.evidence_index, top_k=4, max_per_claim=2,
            retriever_timeout=5.0)
        return {"ok": True, "proposal": proposal,
                "rag_available": self.evidence_index is not None}

    def backup(self):
        """`claim backup` over HTTP; reading a read-only store is allowed."""
        return self.store.backup()

    def backups(self):
        return self.store.backups()

    def audit(self, limit=20, action=None):
        return self.store.audit_entries(limit=limit, action=action)

    def _confirm_or_raise(self, payload):
        if not isinstance(payload, dict):
            raise ClaimStoreError("request body must be a JSON object")
        if payload.get("confirm") is not True:
            raise ClaimStoreError("destructive operations require confirm: true")

    def redact(self, payload):
        """`claim redact` over HTTP; keeps a content-free tombstone."""
        if not self.writable:
            raise DemoReadOnly("this demo is bound to a read-only ledger; restart with --write to redact")
        self._confirm_or_raise(payload)
        return self.store.redact(
            payload.get("claim_id"), cascade=bool(payload.get("cascade")),
            keep_backup=payload.get("keep_backup", True))

    def delete(self, payload):
        """`claim delete` over HTTP; permanent, cascade-aware removal."""
        if not self.writable:
            raise DemoReadOnly("this demo is bound to a read-only ledger; restart with --write to delete")
        self._confirm_or_raise(payload)
        return self.store.delete(
            payload.get("claim_id"), cascade=bool(payload.get("cascade")),
            keep_backup=payload.get("keep_backup", True))

    def evidence(self):
        retrieval = _read_json_file(REPO_ROOT / "benchmarks" / "benchmark-results.json", None)
        wiki = _read_json_file(REPO_ROOT / "benchmarks" / "wiki" / "results.json", None)
        gateway = _read_json_file(REPO_ROOT / "benchmarks" / "gateway" / "results.json", None)
        labels = {
            "Baseline": "Raw transcript lexical",
            "Structured Memory": "Structured memory",
            "Status-aware Memory": "Structured + status-aware",
        }
        methods = []
        if retrieval and isinstance(retrieval.get("results"), dict):
            for key, item in retrieval["results"].items():
                metrics = item.get("metrics", {})
                methods.append({
                    "key": key,
                    "label": labels.get(key, key),
                    "recall1": metrics.get("Recall@1"),
                    "recall5": metrics.get("Recall@5"),
                    "mrr": metrics.get("MRR"),
                    "stale5": metrics.get("stale-hit@5"),
                })
        if not methods:
            methods = [
                {"key": "Baseline", "label": "Raw transcript lexical", "recall1": 0.4167,
                 "recall5": 0.9583, "mrr": 0.6528, "stale5": 0.5417},
                {"key": "Structured Memory", "label": "Structured memory", "recall1": 0.5417,
                 "recall5": 1.0, "mrr": 0.7604, "stale5": 0.5},
                {"key": "Status-aware Memory", "label": "Structured + status-aware", "recall1": 0.7083,
                 "recall5": 0.9167, "mrr": 0.7931, "stale5": 0.0},
            ]
        dataset = retrieval.get("dataset", {}) if retrieval else {}
        return {
            "ok": True,
            "retrieval": {
                "methods": methods,
                "dataset": dataset,
                "evidence": retrieval.get("evidence") if retrieval else None,
                "fixture_sha256": retrieval.get("fixture_sha256") if retrieval else None,
                "source_file": ("benchmarks/benchmark-results.json" if retrieval
                                else "built-in summary (README figures)"),
            },
            "compilebench": {
                "summary": wiki.get("summary", {}) if wiki else {},
                "scope": wiki.get("scope") if wiki else None,
                "limits": wiki.get("limits", []) if wiki else [],
                "source_file": ("benchmarks/wiki/results.json" if wiki
                                else "built-in summary (README figures)"),
            },
            "gateway": gateway,
            "model_calls": 0,
        }


class ConflictClaim(ClaimStoreError):
    def __init__(self, message, conflicts):
        super().__init__(message)
        self.conflicts = conflicts


class DuplicateClaim(ClaimStoreError):
    def __init__(self, message, conflicts):
        super().__init__(message)
        self.conflicts = conflicts


class DemoReadOnly(ClaimStoreError):
    """A write was attempted against a ledger bound without --write."""


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "ClaimLedgerDemo/" + __version__
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("[demo] " + (fmt % args) + "\n")

    @property
    def app(self):
        return self.server.app

    def _send(self, status, body, content_type, *, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _error(self, status, message, error_type="DemoError", **extra):
        payload = {"ok": False, "error": message, "error_type": error_type}
        payload.update(extra)
        self._json(status, payload)

    def _body(self):
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ClaimStoreError("POST bodies must use Content-Type: application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ClaimStoreError("invalid Content-Length")
        if length > MAX_BODY:
            raise ClaimStoreError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ClaimStoreError("request body must be UTF-8 JSON") from exc

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/state":
                return self._json(200, self.app.state(at=query.get("at", [None])[0]))
            if path == "/api/brief":
                try:
                    max_bytes = int(query.get("max_bytes", [str(DEFAULT_MAX_BYTES)])[0])
                except ValueError:
                    return self._error(400, "max_bytes must be an integer")
                return self._json(200, self.app.brief(max_bytes, at=query.get("at", [None])[0]))
            if path == "/api/search":
                include = query.get("include_superseded", ["0"])[0] in ("1", "true", "yes")
                return self._json(200, self.app.search(query.get("q", [""])[0], include))
            if path == "/api/context":
                intent = query.get("intent", ["current"])[0]
                if intent not in ("current", "historical"):
                    return self._error(400, "intent must be current or historical")
                try:
                    max_bytes = int(query.get("max_bytes", ["4096"])[0])
                    top_k = int(query.get("top_k", ["8"])[0])
                    per_claim = int(query.get("max_per_claim", ["2"])[0])
                    timeout = float(query.get("timeout", ["5"])[0])
                except ValueError:
                    return self._error(400, "numeric parameters must be numbers")
                return self._json(200, self.app.context(
                    query.get("q", [""])[0], intent=intent, max_bytes=max_bytes,
                    top_k=top_k, max_per_claim=per_claim, timeout=timeout))
            if path == "/api/evidence":
                return self._json(200, self.app.evidence())
            if path == "/api/backups":
                return self._json(200, self.app.backups())
            if path == "/api/audit":
                raw_limit = query.get("limit", ["20"])[0]
                action = query.get("action", [None])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    return self._error(400, "limit must be an integer")
                return self._json(200, self.app.audit(limit=limit, action=action))
            if path == "/api/health":
                return self._json(200, {"ok": True, "version": __version__})
            return self._error(404, "not found")
        except ClaimStoreError as exc:
            return self._error(400, str(exc), type(exc).__name__)
        except (OSError, ValueError) as exc:
            return self._error(400, str(exc), type(exc).__name__)
        except Exception as exc:  # keep the demo alive, but never pretend success
            if getattr(self.server, "verbose", False):
                import traceback
                traceback.print_exc()
            return self._error(500, "internal demo error: " + str(exc), type(exc).__name__)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            payload = self._body()
            if path == "/api/record":
                return self._json(200, self.app.record(payload))
            if path == "/api/resolve":
                return self._json(200, self.app.resolve(payload))
            if path == "/api/suggest":
                return self._json(200, self.app.suggest(payload))
            if path == "/api/backup":
                return self._json(200, self.app.backup())
            if path == "/api/redact":
                return self._json(200, self.app.redact(payload))
            if path == "/api/delete":
                return self._json(200, self.app.delete(payload))
            if path == "/api/reset":
                return self._json(200, self.app.reset())
            return self._error(404, "not found")
        except ConflictClaim as exc:
            conflicts = [_public_claim(c) for c in exc.conflicts]
            return self._error(
                409, str(exc), "Conflict", conflicts=conflicts,
                suggested_supersedes=[c["claim_id"] for c in conflicts],
            )
        except DuplicateClaim as exc:
            conflicts = [_public_claim(c) for c in exc.conflicts]
            return self._error(409, str(exc), "Duplicate", conflicts=conflicts)
        except DemoReadOnly as exc:
            return self._error(403, str(exc), "ReadOnly")
        except ClaimStoreBusy as exc:
            return self._error(423, str(exc), "Busy")
        except ClaimStoreError as exc:
            return self._error(400, str(exc), type(exc).__name__)
        except (OSError, ValueError) as exc:
            return self._error(400, str(exc), type(exc).__name__)
        except Exception as exc:
            if getattr(self.server, "verbose", False):
                import traceback
                traceback.print_exc()
            return self._error(500, "internal demo error: " + str(exc), type(exc).__name__)

    def _static(self, name, content_type=None):
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return self._error(404, "not found")
        path = STATIC_DIR / name
        if not path.is_file():
            return self._error(404, "not found")
        types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".woff2": "font/woff2",
        }
        self._send(200, path.read_bytes(), content_type or types.get(path.suffix, "application/octet-stream"))


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app, *, verbose=False):
        super().__init__(address, DemoHandler)
        self.app = app
        self.verbose = verbose


def build_server(host="127.0.0.1", port=8765, *, store_path=None, seed=None,
                 writable=None, verbose=False):
    """Create a server without starting it. Returns (server, temp_dir_or_None).

    A supplied store is read-only unless ``writable=True`` and is never seeded
    unless ``seed=True``. Only the disposable demo store seeds by default.
    """
    temp_dir = None
    if store_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="claim-ledger-demo-"))
        store_path = temp_dir / "claims.jsonl"
        mode = "demo"
        writable = True
        if seed is None:
            seed = True
    else:
        store_path = Path(store_path).expanduser()
        writable = bool(writable)
        mode = "read_write" if writable else "read_only"
        if seed is None:
            seed = False
        if not store_path.exists() and not writable and not seed:
            raise ClaimStoreError(
                "store does not exist: " + str(store_path) +
                "; omit --store for the demo, or pass --write/--seed explicitly")
    if seed and not writable:
        raise ClaimStoreError("seeding requires a writable store")
    seeded = False
    if seed and (not store_path.exists() or not store_path.read_text(encoding="utf-8").strip()):
        scenario.seed(store_path)
        seeded = True
    app = DemoApp(store_path, writable=writable, seeded=seeded, mode=mode)
    app.store.claims(status="all")  # validate before serving
    server = DemoServer((host, port), app, verbose=verbose)
    return server, temp_dir


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="claim demo", description="Run the local ClaimLedger demo (zero dependencies).")
    parser.add_argument("--store", help="bind an existing claims.jsonl (read-only unless --write)")
    parser.add_argument("--write", action="store_true",
                        help="allow recording into a store supplied with --store")
    parser.add_argument("--seed", action="store_true",
                        help="with --store, explicitly seed an empty bound store (requires --write)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port; 0 picks a free one (default: 8765)")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--no-seed", action="store_true",
                        help="start the disposable demo store empty instead of the Atlas scenario")
    parser.add_argument("--verbose", action="store_true", help="log HTTP requests")
    args = parser.parse_args(argv)
    if args.store and args.seed and not args.write:
        parser.error("--seed with --store requires --write")

    try:
        if args.store:
            seed = args.seed
            writable = args.write
        else:
            seed = not args.no_seed
            writable = True
        server, temp_dir = build_server(
            args.host, args.port, store_path=args.store, seed=seed,
            writable=writable, verbose=args.verbose)
    except (ClaimStoreError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__},
                         ensure_ascii=False))
        return 1

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    if server.app.mode == "demo":
        store_label = "disposable demo store"
    else:
        store_label = str(server.app.store_path) + (
            " (read-only)" if server.app.mode == "read_only" else " (read/write)")
    print("ClaimLedger demo")
    print("  " + url)
    print("  store: " + store_label + (" (synthetic Atlas scenario)" if server.app.seeded else ""))
    print("  model calls: 0 · Ctrl+C to stop")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

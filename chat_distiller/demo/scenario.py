"""Synthetic project scenario used by the local demo.

The data is handwritten and deliberately boring: it is an ordinary API-platform
project with one storage migration, one auth migration and two open disputes.
Timestamps are fixed so screenshots and the brief stay reproducible. No model is
called; every write still goes through the same JSONL claim store as the CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

SCENARIO = {
    "name": "Atlas API",
    "kicker": "Synthetic project · 7 topics · 12 claims",
    "tagline": "A quarter of decisions for one API platform, with two open disputes.",
    "note": (
        "Handwritten demo data. It records a storage and an auth migration, "
        "keeps two disagreements open, and never calls a model."
    ),
}

CLAIMS = [
    {
        "claim_id": "clm_4b81e2a7c9d30f56",
        "text": "Use SQLite for all Atlas storage",
        "status": "已过期",
        "topic": "database",
        "tags": ["storage", "sqlite"],
        "created_at": "2026-09-12T09:20:00Z",
        "updated_at": "2026-10-02T16:05:00Z",
        "superseded_by": "clm_9f2a6c1d4e8b73a0",
        "superseded_at": "2026-10-02T16:05:00Z",
        "source": "Kickoff notes · 2026-09-12",
        "quote": "Start with SQLite; we can revisit when replication becomes a requirement.",
        "session_hint": "atlas/kickoff-0912",
    },
    {
        "claim_id": "clm_9f2a6c1d4e8b73a0",
        "text": "Use PostgreSQL 16 for all Atlas storage",
        "status": "现行",
        "topic": "database",
        "tags": ["storage", "postgres"],
        "created_at": "2026-10-02T16:05:00Z",
        "updated_at": "2026-10-02T16:05:00Z",
        "superseded_by": None,
        "depends_on": ["clm_5c1e8a3b7d64f290"],
        "source": "Architecture review · 2026-10-02",
        "quote": "SQLite served us in staging. Production needs replication and row-level locks.",
        "session_hint": "atlas/arch-review-1002",
    },
    {
        "claim_id": "clm_5c1e8a3b7d64f290",
        "text": "The platform team owns PostgreSQL operations long-term",
        "status": "现行",
        "topic": "database",
        "tags": ["ownership"],
        "created_at": "2026-10-02T16:05:00Z",
        "updated_at": "2026-10-02T16:05:00Z",
        "superseded_by": None,
        "source": "Architecture review · 2026-10-02",
        "quote": "Postgres only works here if the platform team keeps owning it.",
        "session_hint": "atlas/arch-review-1002",
    },
    {
        "claim_id": "clm_e5d40b7a1c9f2836",
        "text": "Store session tokens in localStorage",
        "status": "已过期",
        "topic": "auth",
        "tags": ["sessions"],
        "created_at": "2026-09-12T09:45:00Z",
        "updated_at": "2026-10-06T10:30:00Z",
        "superseded_by": "clm_c3f81a6d2b705e94",
        "superseded_at": "2026-10-06T10:30:00Z",
        "source": "Kickoff notes · 2026-09-12",
        "quote": "localStorage keeps the SPA simple; revisit before public launch.",
        "session_hint": "atlas/kickoff-0912",
    },
    {
        "claim_id": "clm_c3f81a6d2b705e94",
        "text": "Store session tokens in httpOnly cookies",
        "status": "现行",
        "topic": "auth",
        "tags": ["sessions", "security"],
        "created_at": "2026-10-06T10:30:00Z",
        "updated_at": "2026-10-06T10:30:00Z",
        "superseded_by": None,
        "source": "Security review · 2026-10-06",
        "quote": "The dashboard XSS made localStorage token storage untenable.",
        "session_hint": "atlas/security-review-1006",
    },
    {
        "claim_id": "clm_a17c3d90e5b2f468",
        "text": "API v1 accepts additive fields until the Q2 freeze",
        "status": "现行",
        "topic": "api",
        "tags": ["compatibility", "v1"],
        "created_at": "2026-09-30T11:40:00Z",
        "updated_at": "2026-09-30T11:40:00Z",
        "superseded_by": None,
        "source": "API guild · 2026-09-30",
        "quote": "Additive fields are safe; removals and renames wait for v2.",
        "session_hint": "atlas/api-guild-0930",
    },
    {
        "claim_id": "clm_d28b5f0e4c7a9361",
        "text": "API v1 must stay frozen; no additive fields before Q2",
        "status": "有争议",
        "topic": "api",
        "tags": ["compatibility", "v1"],
        "created_at": "2026-10-09T14:15:00Z",
        "updated_at": "2026-10-09T14:15:00Z",
        "superseded_by": None,
        "source": "API guild · 2026-10-09",
        "quote": "Mobile clients cache schemas aggressively; even additive fields change payloads.",
        "session_hint": "atlas/api-guild-1009",
    },
    {
        "claim_id": "clm_18d5b0c7f2a94e63",
        "text": "Ship behind feature flags on Fridays, never schema migrations",
        "status": "现行",
        "topic": "deployment",
        "tags": ["releases", "flags"],
        "created_at": "2026-10-16T15:10:00Z",
        "updated_at": "2026-10-16T15:10:00Z",
        "superseded_by": None,
        "source": "Release retro · 2026-10-16",
        "quote": "The Friday migration locked the primary for 40 minutes; flags would have hidden it.",
        "session_hint": "atlas/release-retro-1016",
    },
    {
        "claim_id": "clm_3a9e7f2c1b60d845",
        "text": "Rotate the signing key every 90 days with a 7-day overlap",
        "status": "现行",
        "topic": "security",
        "tags": ["keys", "rotation"],
        "created_at": "2026-10-06T10:50:00Z",
        "updated_at": "2026-10-06T10:50:00Z",
        "superseded_by": None,
        "source": "Security review · 2026-10-06",
        "quote": "Two live keys for a week; drop the old one only after the last token expires.",
        "session_hint": "atlas/security-review-1006",
    },
    {
        "claim_id": "clm_2d8f4c6a1e09b573",
        "text": "Rate limits live in the gateway config, never in the app",
        "status": "现行",
        "topic": "api",
        "tags": ["limits", "imported"],
        "created_at": "2026-10-20T13:05:00Z",
        "updated_at": "2026-10-20T13:05:00Z",
        "superseded_by": None,
        "source": "Doubao Work import · 2026-10-20",
        "quote": "Recorded in a Doubao Work session on Friday; the ledger keeps it current for the next agent.",
        "session_hint": "doubao/work-sync-1020",
    },
    {
        "claim_id": "clm_f62b9d0e1a4c8753",
        "text": "The gateway owns request timeouts; workers never retry",
        "status": "有争议",
        "topic": "ops",
        "tags": ["timeouts", "incident-214"],
        "created_at": "2026-10-11T18:20:00Z",
        "updated_at": "2026-10-11T18:20:00Z",
        "superseded_by": None,
        "source": "Incident 214 retro · 2026-10-11",
        "quote": "One request produced three retries after the gateway had already returned 504.",
        "session_hint": "atlas/incident-214",
    },
    {
        "claim_id": "clm_07a1e4c8b93d62f5",
        "text": "Workers own retries; the gateway must not time out",
        "status": "有争议",
        "topic": "ops",
        "tags": ["retries", "incident-214"],
        "created_at": "2026-10-11T18:25:00Z",
        "updated_at": "2026-10-11T18:25:00Z",
        "superseded_by": None,
        "source": "Incident 214 retro · 2026-10-11",
        "quote": "The worker knows whether an operation is idempotent; the gateway does not.",
        "session_hint": "atlas/incident-214",
    },
]

# One-click examples in the Record view. The first text lexically overlaps the
# seeded PostgreSQL claim, so the real guardrail refuses it; nothing is stubbed.
EXAMPLES = {
    "conflict": {
        "text": "Use SQLite for all Atlas production storage",
        "topic": "database",
        "tags": ["storage", "sqlite"],
        "source": "Demo · architecture discussion",
        "quote": "Staging is cheaper on SQLite; can we keep production the same?",
    },
    "clean": {
        "text": "Expire cache entries after 15 minutes",
        "topic": "performance",
        "tags": ["cache"],
        "source": "Demo · performance review",
        "quote": "Most payloads are read far more often than they change.",
    },
    "dispute": {
        "text": "The gateway owns retries and timeouts; workers stay passive",
        "topic": "ops",
        "tags": ["incident-214"],
        "source": "Demo · incident follow-up",
        "quote": "Two owners is what got us here. Pick one.",
    },
    "premise": {
        "text": "The platform team disbands; Atlas moves to managed storage",
        "topic": "database",
        "tags": ["ownership"],
        "source": "Demo · org change",
        "quote": "Nobody is left to run Postgres. Supersede the ownership premise and watch what depends on it.",
    },
}


def claim_rows():
    """Return copies so callers cannot mutate the module-level scenario."""
    return json.loads(json.dumps(CLAIMS, ensure_ascii=False))


def seed(path):
    """Write the scenario to a fresh store path; refuse to seed over existing data."""
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        raise ValueError("demo scenario refuses to overwrite an existing store")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in CLAIMS
    )
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    return path

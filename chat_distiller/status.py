"""The three stored claim statuses — the persistence-layer vocabulary.

Stored as Chinese labels since v0.1; English aliases live in claims.py.
This module is a leaf so claims and context can share the constants
without an import cycle.
"""
from __future__ import annotations

STATUS_CURRENT = "现行"
STATUS_SUPERSEDED = "已过期"
STATUS_DISPUTED = "有争议"
STATUSES = (STATUS_CURRENT, STATUS_SUPERSEDED, STATUS_DISPUTED)

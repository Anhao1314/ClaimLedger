"""Deterministic policy: a typed answer in, an action out. v2.1.

v2 retired the score formula. v2.1 retires the *global* contradiction signal:
conflicts are localized pairwise (the validated `relation` question), and any
record that is part of a confirmed contradicting pair goes to review.

What remains here is one rule: a confident governing claim may promote
`review` to `admit` — never `exclude`, and never a conflicted record.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ADMIT = "admit"
REVIEW = "review"
EXCLUDE = "exclude"
ACTIONS = (ADMIT, REVIEW, EXCLUDE)


@dataclass(frozen=True)
class Policy:
    version: str = "v2.1"
    governing_at: float = 0.80

    def __post_init__(self) -> None:
        if not 0.0 <= self.governing_at <= 1.0:
            raise ValueError("governing_at must be within [0, 1]")

    def action(self, choice: str, *, governing: bool = False) -> str:
        if choice not in ACTIONS:
            raise ValueError(f"unknown action: {choice!r}")
        if governing and choice == REVIEW:
            return ADMIT
        return choice

    def to_dict(self) -> dict:
        return asdict(self)
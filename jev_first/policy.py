"""Deterministic policy: probability in, action out.

The asymmetry is deliberate and belongs here, not in a prompt:

* wrongly suppressing a valid claim is a silent failure — the agent proceeds
  without a real constraint;
* wrongly retaining a stale claim is visible — it appears in the result.

So a low score excludes, but any meaningful contradiction forces review rather
than automatic exclusion. Thresholds are data (versioned), not code constants:
calibration evidence has to be able to replay them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ADMIT = "admit"
REVIEW = "review"
EXCLUDE = "exclude"
ACTIONS = (ADMIT, REVIEW, EXCLUDE)


@dataclass(frozen=True)
class Policy:
    version: str = "v1"
    admit_at: float = 0.60
    review_at: float = 0.30
    contradiction_review_at: float = 0.70

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_at <= self.admit_at <= 1.0:
            raise ValueError("require 0 <= review_at <= admit_at <= 1")
        if not 0.0 <= self.contradiction_review_at <= 1.0:
            raise ValueError("contradiction_review_at must be within [0, 1]")

    def action(self, score: float, *, contradiction: float = 0.0) -> str:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be within [0, 1]")
        if score < self.review_at:
            return EXCLUDE
        if contradiction >= self.contradiction_review_at:
            return REVIEW
        if score >= self.admit_at:
            return ADMIT
        return REVIEW

    def to_dict(self) -> dict:
        return asdict(self)
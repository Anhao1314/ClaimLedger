"""Deterministic policy: a typed answer in, an action out. v2.

The score formula (p(applies) × p(holds)) is retired — see
contracts/questions.v1.json "retired". The model now answers `admit` directly
as a three-way choice; this policy only applies two structural rules:

* **Outage and contradiction are not evidence.** A transport failure fails open
  to review (handled by the judge); a contradiction in the candidate set forces
  review and makes `admit` structurally impossible for that decision.
* **Governing is a tie-breaker, not a veto.** A confident governing claim may
  promote `review` to `admit` — but never overrides `exclude`, and never
  overrides the contradiction rule.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ADMIT = "admit"
REVIEW = "review"
EXCLUDE = "exclude"
ACTIONS = (ADMIT, REVIEW, EXCLUDE)


@dataclass(frozen=True)
class Policy:
    version: str = "v2"
    contradiction_review_at: float = 0.70
    governing_at: float = 0.80

    def __post_init__(self) -> None:
        for name in ("contradiction_review_at", "governing_at"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")

    def action(self, choice: str, *, contradiction: float = 0.0,
               governing: bool = False) -> str:
        """Apply the structural rules to the model's argmax choice."""
        if choice not in ACTIONS:
            raise ValueError(f"unknown action: {choice!r}")
        if not 0.0 <= contradiction <= 1.0:
            raise ValueError("contradiction must be within [0, 1]")
        if choice == EXCLUDE:
            return EXCLUDE
        # `admit` and an unresolved contradiction are mutually exclusive by
        # construction: the conflict must be looked at, not auto-resolved by a
        # governing signal.
        if contradiction >= self.contradiction_review_at:
            return REVIEW
        if governing and choice == REVIEW:
            return ADMIT
        return choice

    def to_dict(self) -> dict:
        return asdict(self)
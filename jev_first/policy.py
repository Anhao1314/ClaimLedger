"""Deterministic policy: a typed answer in, an action out. v2.2.

History of the rules, each added by a measurement:

* v2    — the score formula is retired; the model answers `admit` directly.
* v2.1  — conflicts are localized pairwise; a confident governing claim may
          promote review to admit, never a conflicted record.
* v2.2  — **margin rule**: when the top-two options of a choice are close, the
          answer is not confident enough to act on. The 5x5 stability check
          (borderline-stability.json) showed a ~17% flip rate on a borderline
          pair while unambiguous pairs never flip: argmax alone lets sampling
          noise become a decision. Thin margins go to review.

What remains invariant: wrong suppression is silent, wrong retention is
visible — so every uncertain path lands on review, never on exclude.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ADMIT = "admit"
REVIEW = "review"
EXCLUDE = "exclude"
ACTIONS = (ADMIT, REVIEW, EXCLUDE)


@dataclass(frozen=True)
class Policy:
    version: str = "v2.2"
    governing_at: float = 0.80
    margin: float = 0.20

    def __post_init__(self) -> None:
        for name in ("governing_at", "margin"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")

    def action(self, choice: str, *, governing: bool = False,
               thin_margin: bool = False) -> str:
        if choice not in ACTIONS:
            raise ValueError(f"unknown action: {choice!r}")
        if thin_margin:
            return REVIEW
        if governing and choice == REVIEW:
            return ADMIT
        return choice

    def to_dict(self) -> dict:
        return asdict(self)
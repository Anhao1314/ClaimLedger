"""The question library: one request, many typed questions.

Jev answers every question in a request in parallel against the same `state`.
Because the measured round-trip is 1.6-4.4 s, asking once per claim is not
viable: a decision must be a single round trip.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from chat_distiller import jev

RESERVED_IDS = ("governing", "contradiction")
MAX_CHOICES = 255


def render_state(task: str, claims: Sequence[Mapping[str, Any]], *,
                 include_status: bool = False) -> str:
    """Render the task and the candidate claims as plain text.

    ``include_status`` is an experimental knob. Leaving it off is the honest
    default for a Jev-first design: the model must judge from content, not from
    a status field the old runtime already decided.
    """
    lines: List[str] = [f"TASK: {task.strip()}", "", "MEMORY CLAIMS:"]
    for claim in claims:
        text = str(claim["text"]).strip()
        if include_status and claim.get("status"):
            lines.append(f"- {claim['claim_id']}: {text} [recorded status: {claim['status']}]")
        else:
            lines.append(f"- {claim['claim_id']}: {text}")
    return "\n".join(lines)


def build_questions(claims: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build the typed question set for one decision."""
    if not claims:
        raise ValueError("at least one claim is required")
    if len(claims) + 1 > MAX_CHOICES:
        raise ValueError(f"too many claims for one request (max {MAX_CHOICES - 1})")
    questions: Dict[str, Dict[str, Any]] = {}
    criteria: Dict[str, str] = {}
    for claim in claims:
        claim_id = str(claim["claim_id"])
        if claim_id in RESERVED_IDS:
            raise ValueError(f"reserved claim id: {claim_id}")
        text = str(claim["text"]).strip()
        questions[f"applies::{claim_id}"] = jev.noul(
            f"The claim {claim_id} places a constraint on how the TASK must be done."
        )
        questions[f"holds::{claim_id}"] = jev.noul(
            f"The claim {claim_id} is still in force for the TASK, even considering "
            f"the other claims listed."
        )
        criteria[claim_id] = text[:160]
    criteria["none"] = "No single claim governs this task"
    questions["governing"] = jev.choice(
        "Which single claim should govern the TASK", criteria)
    questions["contradiction"] = jev.noul(
        "Two or more of the listed claims contradict each other for this TASK."
    )
    return questions
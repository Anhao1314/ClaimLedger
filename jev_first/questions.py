"""State rendering for a decision. The claim's stored status (if any) is never
shown: validity is the model's judgment, not the legacy runtime's label."""
from __future__ import annotations

from typing import Any, List, Mapping, Sequence


def render_state(task: str, records: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = [f"TASK: {task.strip()}", "", "MEMORY CLAIMS:"]
    for record in records:
        lines.append(f"- {record['record_id']}: {str(record['text']).strip()}")
    return "\n".join(lines)
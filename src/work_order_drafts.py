from __future__ import annotations

from typing import Any


ALLOWED_PRIORITIES = {
    "routine",
    "medium",
    "high",
    "urgent",
    "requires_review",
}


def draft_from_analysis(analysis: Any) -> dict[str, Any]:
    """Build a persisted work-order draft from validated AI output."""
    if not isinstance(analysis, dict):
        raise ValueError("A valid AI analysis is required to create a draft.")

    if analysis.get("ai_generated") is not True:
        raise ValueError("Only a validated AI analysis can create a work-order draft.")

    ai_draft = analysis.get("draft_work_order")
    if not isinstance(ai_draft, dict):
        raise ValueError("The analysis does not contain a valid work-order draft.")

    summary = ai_draft.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("The analysis work-order summary is missing.")

    priority = ai_draft.get("priority", analysis.get("proposed_priority"))
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError("The analysis work-order priority is invalid.")

    actions = ai_draft.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, str) for action in actions
    ):
        raise ValueError("The analysis work-order actions are invalid.")

    if not actions:
        steps = analysis.get("inspection_steps", [])
        if isinstance(steps, list):
            actions = [
                step["action"]
                for step in steps
                if isinstance(step, dict)
                and isinstance(step.get("action"), str)
                and step["action"].strip()
            ]

    if not actions:
        raise ValueError("The analysis contains no proposed maintenance actions.")

    citations = ai_draft.get("evidence_citations", [])
    if not isinstance(citations, list) or any(
        not isinstance(citation, str) for citation in citations
    ):
        raise ValueError("The analysis work-order citations are invalid.")

    return {
        "summary": summary.strip(),
        "priority": priority,
        "actions": [action.strip() for action in actions if action.strip()],
        "evidence_citations": citations,
    }

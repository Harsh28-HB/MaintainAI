from __future__ import annotations

from typing import Any


ALLOWED_PRIORITIES = {
    "routine",
    "medium",
    "high",
    "urgent",
    "requires_review",
}


def _unique_actions(actions: list[str]) -> list[str]:
    """Remove exact duplicate instructions while preserving their order."""
    unique = []
    seen = set()
    for action in actions:
        normalized = action.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def draft_from_analysis(analysis: Any) -> dict[str, Any]:
    """Build a persisted draft from validated AI or deterministic demo output."""
    if not isinstance(analysis, dict):
        raise ValueError(
            "A valid AI analysis or deterministic demo guidance is required "
            "to create a draft."
        )

    validated_ai = analysis.get("ai_generated") is True
    deterministic_demo = (
        analysis.get("ai_provider") == "demo"
        and analysis.get("ai_generated") is False
    )
    if not (validated_ai or deterministic_demo):
        raise ValueError(
            "Only validated AI analysis or deterministic demo guidance can "
            "create a work-order draft."
        )

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
        "actions": _unique_actions(actions),
        "evidence_citations": citations,
    }


def draft_from_issue(issue: Any) -> dict[str, Any]:
    """Build a review-only draft from a persisted issue without analysis."""
    if not isinstance(issue, dict):
        raise ValueError("A saved issue is required to create a work-order draft.")

    description = issue.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("The saved issue description is missing.")

    return {
        "summary": "Technician review of reported issue",
        "priority": "requires_review",
        "actions": [
            "Review the saved issue report and determine the required "
            "maintenance work."
        ],
        "evidence_citations": [],
    }

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

logger = logging.getLogger("maintainai.app")


def report_issue_workflow_error(
    error: Exception,
    provider: str,
    sensitive_values: Iterable[str | None],
    show_error: Callable[[str], object],
) -> None:
    """Display an actionable workflow error and log only sanitized details."""
    message = str(error)
    for sensitive_value in sensitive_values:
        if sensitive_value and len(sensitive_value) >= 3:
            message = message.replace(sensitive_value, "[redacted]")
    message = " ".join(message.split())[:500]

    logger.warning(
        "Issue workflow failure: provider=%s exception_type=%s message=%s",
        provider,
        type(error).__name__,
        message,
    )
    show_error(message)

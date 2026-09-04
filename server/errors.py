"""Domain errors.

These are intentionally free of any MCP SDK import. Providers raise them; `tools.py` is the
only module that knows how to turn them into an MCP `ToolError`. That keeps the provider layer
testable on its own and means the guardrail/agent layers can catch them directly later.
"""

from __future__ import annotations

from datetime import datetime


class IssuesError(Exception):
    """Base class for every anticipated failure in this server."""


class ConfigError(IssuesError):
    """Bad or missing configuration. Raised at startup, never mid-request."""


class NotFoundError(IssuesError):
    """The requested issue/label/milestone does not exist."""


class RateLimitError(IssuesError):
    """Upstream rate limit exhausted.

    Carries the reset time so the message handed to the model is actionable. We deliberately do
    not sleep and retry: a tool call that blocks for 40 minutes stalls the agent loop with no
    explanation, and a planner can route around a stated failure but not a hang.
    """

    def __init__(self, reset_at: datetime | None = None, limit: int | None = None) -> None:
        self.reset_at = reset_at
        self.limit = limit
        when = reset_at.isoformat() if reset_at else "an unknown time"
        cap = f" (limit {limit}/hr)" if limit else ""
        super().__init__(
            f"GitHub API rate limit exhausted{cap}; it resets at {when}. "
            "Do not retry before then -- either wait, or answer from data already retrieved."
        )


class UpstreamError(IssuesError):
    """Upstream returned an unusable response after retries."""

    def __init__(self, status: int | None, detail: str = "") -> None:
        self.status = status
        suffix = f": {detail}" if detail else ""
        super().__init__(f"GitHub API request failed (HTTP {status}){suffix}")

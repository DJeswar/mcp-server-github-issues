"""MCP server exposing a GitHub repository's Issues as agent tools.

Deliberately dependency-light at package level: the guardrail layer (Phase 4c) imports
UNTRUSTED_FIELDS from here, and it must not have to pull in httpx or the MCP SDK to do it.
"""

__version__ = "0.1.0"

#: Exactly which model fields carry text authored by arbitrary GitHub users.
#:
#: This is the single source of truth for the trust boundary. The Phase 4c inbound guardrail
#: imports it instead of keeping its own list -- two lists drift, and the failure mode is a
#: guardrail that scans issue bodies but not comments.
#:
#: Labels and milestones are included on purpose: anyone with write access to a repo can put an
#: injection payload in a label description, and it reaches the planner through list_labels.
UNTRUSTED_FIELDS: dict[str, tuple[str, ...]] = {
    "IssueSummary": ("title",),
    "IssueDetail": ("title", "body"),
    "Comment": ("body",),
    "Label": ("name", "description"),
    "Milestone": ("title", "description"),
}

__all__ = ["UNTRUSTED_FIELDS", "__version__"]

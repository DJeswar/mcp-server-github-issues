"""Pydantic models: the tool output shapes and the internal query objects.

Both providers return these exact types. Tool return annotations use them, which is what makes
the MCP SDK emit an `output_schema` and populate `structured_content`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

IssueState = Literal["open", "closed"]
StateFilter = Literal["open", "closed", "all"]
SortField = Literal["created", "updated", "comments"]
Direction = Literal["asc", "desc"]
MilestoneSort = Literal["due_on", "completeness"]

Backend = Literal["fixture", "github"]


# --------------------------------------------------------------------------- output models


class Label(BaseModel):
    name: str
    color: str | None = None
    description: str | None = None


class Milestone(BaseModel):
    number: int
    title: str
    state: IssueState
    description: str | None = None
    due_on: datetime | None = None
    open_issues: int = 0
    closed_issues: int = 0


class Comment(BaseModel):
    id: int
    author: str | None = Field(None, description="GitHub login, or null if the account is gone.")
    created_at: datetime
    updated_at: datetime
    body: str
    body_truncated: bool = False


class IssueSummary(BaseModel):
    """Compact issue record. No body -- call get_issue for full text."""

    number: int
    title: str
    state: IssueState
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    milestone: str | None = None
    comments: int = Field(0, description="Number of comments on the issue.")
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    days_since_update: float = Field(
        0.0,
        description=(
            "Whole and fractional days between updated_at and the envelope's fetched_at. "
            "Provided so staleness questions do not depend on the model doing date arithmetic."
        ),
    )
    url: str | None = None


class IssueDetail(IssueSummary):
    """Full issue record, including untrusted body text and optionally its comments."""

    body: str = ""
    body_truncated: bool = False
    references: list[int] = Field(
        default_factory=list,
        description=(
            "Issue numbers referenced as #N in the body, in order of first appearance. "
            "Parsed for multi-hop questions ('what blocks this?'); it is not a GitHub link type."
        ),
    )
    comment_list: list[Comment] = Field(
        default_factory=list,
        description="Comments actually returned, subject to comment_limit.",
    )


ItemT = TypeVar("ItemT")


class Envelope(BaseModel, Generic[ItemT]):
    """Shared wrapper for every tool result.

    `has_more`/`next_page` exist so pagination is the planner's explicit decision. `notes`
    records anything the server did to the data -- exclusions, truncation, ranking
    approximations -- because silent transformation is how an agent confidently misreports.
    """

    repo: str
    backend: Backend
    fetched_at: datetime
    count: int = Field(0, description="Number of items in this page, not the total available.")
    has_more: bool = False
    next_page: int | None = None
    items: list[ItemT] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- query models


class ListIssuesQuery(BaseModel):
    state: StateFilter = "open"
    labels: list[str] | None = None
    assignee: str | None = None
    milestone: str | None = None
    since: datetime | None = None
    sort: SortField = "created"
    direction: Direction = "desc"
    limit: int = Field(30, ge=1, le=100)
    page: int = Field(1, ge=1)


class GetIssueQuery(BaseModel):
    number: int = Field(..., ge=1)
    include_comments: bool = True
    comment_limit: int = Field(20, ge=1, le=100)
    max_body_chars: int = Field(4000, ge=100, le=50_000)


class SearchIssuesQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=256)
    state: StateFilter = "all"
    limit: int = Field(20, ge=1, le=50)
    page: int = Field(1, ge=1)


class ListLabelsQuery(BaseModel):
    limit: int = Field(100, ge=1, le=100)
    page: int = Field(1, ge=1)


class ListMilestonesQuery(BaseModel):
    state: StateFilter = "open"
    sort: MilestoneSort = "due_on"
    limit: int = Field(100, ge=1, le=100)
    page: int = Field(1, ge=1)

"""Raw GitHub-shaped JSON -> models.

Both providers call these functions. The fixture corpus is stored in GitHub's response shape
precisely so this is the *only* conversion path -- which makes backend parity structural rather
than something a test has to chase.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import Comment, IssueDetail, IssueSummary, Label, Milestone

#: `#123` not preceded by a word character, so `abc#1` and URLs ending in #1 do not match.
_REF_RE = re.compile(r"(?<![\w/])#(\d+)\b")


def parse_dt(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def truncate(text: str | None, max_chars: int) -> tuple[str, bool]:
    """Return (text, was_truncated). A single 60k-char issue body should not eat the context."""
    body = text or ""
    if len(body) <= max_chars:
        return body, False
    return body[:max_chars], True


def parse_references(body: str | None) -> list[int]:
    """Issue numbers referenced as #N, de-duplicated, in order of first appearance."""
    seen: dict[int, None] = {}
    for match in _REF_RE.finditer(body or ""):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


def days_between(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds() / 86400.0, 2)


def is_pull_request(raw: dict[str, Any]) -> bool:
    """GitHub's issues endpoints return PRs as issues; they are excluded everywhere."""
    return bool(raw.get("pull_request"))


def _labels(raw: dict[str, Any]) -> list[str]:
    out = []
    for lab in raw.get("labels") or []:
        out.append(lab if isinstance(lab, str) else str(lab.get("name", "")))
    return [name for name in out if name]


def _assignees(raw: dict[str, Any]) -> list[str]:
    logins = [
        (a or {}).get("login") for a in (raw.get("assignees") or []) if isinstance(a, dict)
    ]
    if not logins and isinstance(raw.get("assignee"), dict):
        logins = [raw["assignee"].get("login")]
    return [login for login in logins if login]


def _milestone_title(raw: dict[str, Any]) -> str | None:
    ms = raw.get("milestone")
    if isinstance(ms, dict):
        return ms.get("title")
    return ms if isinstance(ms, str) else None


def to_summary(raw: dict[str, Any], now: datetime) -> IssueSummary:
    updated = parse_dt(raw.get("updated_at")) or parse_dt(raw.get("created_at"))
    created = parse_dt(raw.get("created_at")) or updated
    assert created is not None and updated is not None, "issue is missing both timestamps"
    return IssueSummary(
        number=int(raw["number"]),
        title=raw.get("title") or "",
        state=("closed" if raw.get("state") == "closed" else "open"),
        labels=_labels(raw),
        assignees=_assignees(raw),
        milestone=_milestone_title(raw),
        comments=int(raw.get("comments") or 0),
        created_at=created,
        updated_at=updated,
        closed_at=parse_dt(raw.get("closed_at")),
        days_since_update=days_between(now, updated),
        url=raw.get("html_url"),
    )


def to_detail(
    raw: dict[str, Any], now: datetime, max_body_chars: int
) -> tuple[IssueDetail, bool]:
    """Return (detail, body_was_truncated). Comments are attached by the caller."""
    summary = to_summary(raw, now)
    body, truncated = truncate(raw.get("body"), max_body_chars)
    detail = IssueDetail(
        **summary.model_dump(),
        body=body,
        body_truncated=truncated,
        # references come from the FULL body: truncation must not hide a dependency
        references=parse_references(raw.get("body")),
    )
    return detail, truncated


def to_comment(raw: dict[str, Any], max_body_chars: int) -> tuple[Comment, bool]:
    body, truncated = truncate(raw.get("body"), max_body_chars)
    created = parse_dt(raw.get("created_at"))
    updated = parse_dt(raw.get("updated_at")) or created
    assert created is not None and updated is not None, "comment is missing timestamps"
    user = raw.get("user") or {}
    return (
        Comment(
            id=int(raw.get("id") or 0),
            author=user.get("login") if isinstance(user, dict) else None,
            created_at=created,
            updated_at=updated,
            body=body,
            body_truncated=truncated,
        ),
        truncated,
    )


def to_label(raw: dict[str, Any]) -> Label:
    return Label(
        name=raw.get("name") or "",
        color=raw.get("color"),
        description=raw.get("description"),
    )


def to_milestone(raw: dict[str, Any]) -> Milestone:
    return Milestone(
        number=int(raw.get("number") or 0),
        title=raw.get("title") or "",
        state=("closed" if raw.get("state") == "closed" else "open"),
        description=raw.get("description"),
        due_on=parse_dt(raw.get("due_on")),
        open_issues=int(raw.get("open_issues") or 0),
        closed_issues=int(raw.get("closed_issues") or 0),
    )

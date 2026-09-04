"""The seam's load-bearing invariant.

Both providers must return identical model types with identical field semantics. Everything
built against fixtures — the LangGraph agent, the guardrails, the eval suite — silently diverges
on live data if this breaks, which is the exact failure the provider seam exists to prevent.

Scope, stated honestly: this compares the *conversion and envelope* path by feeding both
providers the same raw upstream rows. It does not re-test filtering, because GitHub does that
server-side and there is nothing local to compare against; filter/sort/paginate semantics are
covered by tests/test_fixture_provider.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import respx

from server.config import FIXTURE_DIR
from server.models import Envelope, GetIssueQuery, IssueDetail, IssueSummary, ListIssuesQuery
from server.providers.github import GitHubProvider

REPO = "example/issues-demo"
BASE = "https://api.github.com"
FIXTURE_NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)

RAW_ISSUES = json.loads((FIXTURE_DIR / "issues.json").read_text(encoding="utf-8"))
RAW_COMMENTS = json.loads((FIXTURE_DIR / "comments.json").read_text(encoding="utf-8"))


class FrozenGitHubProvider(GitHubProvider):
    """Wall-clock `now()` would make days_since_update incomparable."""

    def now(self) -> datetime:
        return FIXTURE_NOW


def raw_by_number(*numbers: int) -> list[dict]:
    index = {int(row["number"]): row for row in RAW_ISSUES}
    return [index[n] for n in numbers]


class TestListIssuesParity:
    @respx.mock
    async def test_identical_items_for_the_worked_example(self, provider):
        """The blocked-v2 query, served to the live provider as GitHub would return it."""
        fixture_env = await provider.list_issues(
            ListIssuesQuery(state="open", labels=["blocked"], milestone="v2")
        )
        assert [i.number for i in fixture_env.items] == [5, 3, 8]

        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=raw_by_number(5, 3, 8))
        )
        live = FrozenGitHubProvider(repo=REPO)
        live_env = await live.list_issues(
            ListIssuesQuery(state="open", labels=["blocked"], milestone="v2")
        )
        await live.aclose()

        assert fixture_env.items == live_env.items

    @respx.mock
    async def test_item_types_are_the_same_class(self, provider):
        fixture_env = await provider.list_issues(ListIssuesQuery(limit=1))
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=raw_by_number(12))
        )
        live = FrozenGitHubProvider(repo=REPO)
        live_env = await live.list_issues(ListIssuesQuery(limit=1))
        await live.aclose()

        assert type(fixture_env.items[0]) is type(live_env.items[0]) is IssueSummary

    @respx.mock
    async def test_envelope_shape_is_identical(self, provider):
        fixture_env = await provider.list_issues(ListIssuesQuery(limit=1))
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=raw_by_number(12))
        )
        live = FrozenGitHubProvider(repo=REPO)
        live_env = await live.list_issues(ListIssuesQuery(limit=1))
        await live.aclose()

        # `notes` content is provider-specific by design; the field set is not
        assert set(fixture_env.model_dump()) == set(live_env.model_dump())
        assert fixture_env.backend == "fixture" and live_env.backend == "github"


class TestGetIssueParity:
    @respx.mock
    async def test_identical_detail_and_comments(self, provider):
        fixture_env = await provider.get_issue(GetIssueQuery(number=3))

        respx.get(f"{BASE}/repos/{REPO}/issues/3").mock(
            return_value=httpx.Response(200, json=raw_by_number(3)[0])
        )
        respx.get(f"{BASE}/repos/{REPO}/issues/3/comments").mock(
            return_value=httpx.Response(200, json=RAW_COMMENTS["3"])
        )
        live = FrozenGitHubProvider(repo=REPO)
        live_env = await live.get_issue(GetIssueQuery(number=3))
        await live.aclose()

        assert fixture_env.items == live_env.items
        assert type(fixture_env.items[0]) is type(live_env.items[0]) is IssueDetail

    @respx.mock
    async def test_truncation_behaves_the_same(self, provider):
        fixture_env = await provider.get_issue(
            GetIssueQuery(number=3, max_body_chars=120, include_comments=False)
        )
        respx.get(f"{BASE}/repos/{REPO}/issues/3").mock(
            return_value=httpx.Response(200, json=raw_by_number(3)[0])
        )
        live = FrozenGitHubProvider(repo=REPO)
        live_env = await live.get_issue(
            GetIssueQuery(number=3, max_body_chars=120, include_comments=False)
        )
        await live.aclose()

        assert fixture_env.items[0].body_truncated is live_env.items[0].body_truncated is True
        assert fixture_env.items[0].body == live_env.items[0].body
        # references are parsed from the untruncated body in both providers
        assert fixture_env.items[0].references == live_env.items[0].references == [5]


def test_both_providers_declare_the_same_return_annotations():
    """A drift in declared types would let one backend return a different shape."""
    from server.providers.base import IssuesProvider
    from server.providers.fixture import FixtureProvider

    expected = {
        "list_issues": "Envelope[IssueSummary]",
        "get_issue": "Envelope[IssueDetail]",
        "search_issues": "Envelope[IssueSummary]",
        "list_labels": "Envelope[Label]",
        "list_milestones": "Envelope[Milestone]",
    }
    for name, want in expected.items():
        # `from __future__ import annotations` means these are strings
        got = {
            cls.__name__: cls.__dict__[name].__annotations__["return"]
            for cls in (IssuesProvider, FixtureProvider, GitHubProvider)
        }
        assert set(got.values()) == {want}, f"{name} return annotation drifted: {got}"

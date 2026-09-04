"""Live-path provider, exercised against a mocked transport (no network, no credentials)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from server.errors import NotFoundError, RateLimitError, UpstreamError
from server.models import GetIssueQuery, ListIssuesQuery, SearchIssuesQuery
from server.providers.github import GitHubProvider

REPO = "octo/demo"
BASE = "https://api.github.com"

ISSUE = {
    "number": 42,
    "title": "A real issue",
    "state": "open",
    "body": "Blocked by #7.",
    "labels": [{"name": "bug", "color": "d73a4a", "description": "d"}],
    "assignees": [{"login": "alice"}],
    "milestone": {"number": 2, "title": "v2", "state": "open"},
    "comments": 1,
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-25T00:00:00Z",
    "closed_at": None,
    "html_url": f"https://github.com/{REPO}/issues/42",
}

PULL = {**ISSUE, "number": 43, "pull_request": {"url": "..."}}


async def _nosleep(_seconds: float) -> None:
    """Keep retry tests instant."""


def make_provider(token: str | None = None, **kw) -> GitHubProvider:
    return GitHubProvider(repo=REPO, token=token, sleep=_nosleep, **kw)


class TestAuth:
    @respx.mock
    async def test_no_authorization_header_without_a_token(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = make_provider(token=None)
        await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert "authorization" not in route.calls[0].request.headers

    @respx.mock
    async def test_bearer_header_when_a_token_is_present(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = make_provider(token="ghp_example")
        await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert route.calls[0].request.headers["authorization"] == "Bearer ghp_example"

    @respx.mock
    async def test_api_version_header_is_pinned(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = make_provider()
        await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert route.calls[0].request.headers["x-github-api-version"] == "2022-11-28"


class TestListIssues:
    @respx.mock
    async def test_maps_fields_and_records_backend(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[ISSUE])
        )
        provider = make_provider()
        env = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()

        assert env.backend == "github"
        assert env.repo == REPO
        item = env.items[0]
        assert (item.number, item.title, item.state) == (42, "A real issue", "open")
        assert item.labels == ["bug"]
        assert item.assignees == ["alice"]
        assert item.milestone == "v2"

    @respx.mock
    async def test_labels_are_sent_comma_separated(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        provider = make_provider()
        await provider.list_issues(ListIssuesQuery(labels=["bug", "blocked"]))
        await provider.aclose()
        assert route.calls[0].request.url.params["labels"] == "bug,blocked"

    @respx.mock
    async def test_pull_requests_are_excluded_and_reported(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[ISSUE, PULL])
        )
        provider = make_provider()
        env = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()

        assert [i.number for i in env.items] == [42]
        assert any("1 pull request(s)" in n for n in env.notes)

    @respx.mock
    async def test_has_more_comes_from_the_link_header(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[ISSUE],
                headers={"link": f'<{BASE}/repos/{REPO}/issues?page=2>; rel="next"'},
            )
        )
        provider = make_provider()
        env = await provider.list_issues(ListIssuesQuery(page=1))
        await provider.aclose()
        assert env.has_more is True and env.next_page == 2

    @respx.mock
    async def test_no_link_header_means_no_more(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=[ISSUE])
        )
        provider = make_provider()
        env = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert env.has_more is False and env.next_page is None


class TestGetIssue:
    @respx.mock
    async def test_fetches_comments_and_parses_references(self):
        respx.get(f"{BASE}/repos/{REPO}/issues/42").mock(
            return_value=httpx.Response(200, json=ISSUE)
        )
        respx.get(f"{BASE}/repos/{REPO}/issues/42/comments").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "user": {"login": "bob"},
                        "created_at": "2026-07-02T00:00:00Z",
                        "updated_at": "2026-07-02T00:00:00Z",
                        "body": "a comment",
                    }
                ],
            )
        )
        provider = make_provider()
        env = await provider.get_issue(GetIssueQuery(number=42))
        await provider.aclose()

        detail = env.items[0]
        assert detail.references == [7]
        assert [c.author for c in detail.comment_list] == ["bob"]
        assert any("untrusted" in n for n in env.notes)

    @respx.mock
    async def test_a_pull_request_number_is_rejected_as_not_an_issue(self):
        respx.get(f"{BASE}/repos/{REPO}/issues/43").mock(
            return_value=httpx.Response(200, json=PULL)
        )
        provider = make_provider()
        with pytest.raises(NotFoundError, match="is a pull request"):
            await provider.get_issue(GetIssueQuery(number=43))
        await provider.aclose()

    @respx.mock
    async def test_comments_not_fetched_when_disabled(self):
        respx.get(f"{BASE}/repos/{REPO}/issues/42").mock(
            return_value=httpx.Response(200, json=ISSUE)
        )
        comments = respx.get(f"{BASE}/repos/{REPO}/issues/42/comments")
        provider = make_provider()
        env = await provider.get_issue(GetIssueQuery(number=42, include_comments=False))
        await provider.aclose()
        assert not comments.called
        assert any("include_comments=false" in n for n in env.notes)


class TestSearch:
    @respx.mock
    async def test_builds_the_qualified_query(self):
        route = respx.get(f"{BASE}/search/issues").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []})
        )
        provider = make_provider()
        await provider.search_issues(SearchIssuesQuery(query="rate limit", state="open"))
        await provider.aclose()
        q = route.calls[0].request.url.params["q"]
        assert q == f"repo:{REPO} is:issue state:open rate limit"

    @respx.mock
    async def test_has_more_from_total_count(self):
        respx.get(f"{BASE}/search/issues").mock(
            return_value=httpx.Response(200, json={"total_count": 100, "items": [ISSUE]})
        )
        provider = make_provider()
        env = await provider.search_issues(SearchIssuesQuery(query="x", limit=20, page=1))
        await provider.aclose()
        assert env.has_more is True

    @respx.mock
    async def test_incomplete_results_is_surfaced(self):
        respx.get(f"{BASE}/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 1, "incomplete_results": True, "items": [ISSUE]},
            )
        )
        provider = make_provider()
        env = await provider.search_issues(SearchIssuesQuery(query="x"))
        await provider.aclose()
        assert any("incomplete_results" in n for n in env.notes)


class TestErrorHandling:
    @respx.mock
    async def test_rate_limit_exhaustion_names_the_reset_time_and_does_not_retry(self):
        reset = int(datetime(2026, 8, 1, 10, tzinfo=timezone.utc).timestamp())
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": str(reset),
                    "x-ratelimit-limit": "60",
                },
            )
        )
        provider = make_provider()
        with pytest.raises(RateLimitError) as exc:
            await provider.list_issues(ListIssuesQuery())
        await provider.aclose()

        assert "2026-08-01T10:00:00" in str(exc.value)
        assert "limit 60/hr" in str(exc.value)
        # a hard rate limit is not retried -- retrying cannot help before the reset
        assert route.call_count == 1

    @respx.mock
    async def test_404_becomes_not_found(self):
        respx.get(f"{BASE}/repos/{REPO}/issues/1").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        provider = make_provider()
        with pytest.raises(NotFoundError):
            await provider.get_issue(GetIssueQuery(number=1))
        await provider.aclose()

    @respx.mock
    async def test_server_error_is_retried_then_raises_upstream(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            return_value=httpx.Response(503, json={"message": "unavailable"})
        )
        provider = make_provider(max_attempts=3)
        with pytest.raises(UpstreamError, match="503"):
            await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert route.call_count == 3

    @respx.mock
    async def test_transient_server_error_then_success(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=[
                httpx.Response(500, json={"message": "boom"}),
                httpx.Response(200, json=[ISSUE]),
            ]
        )
        provider = make_provider(max_attempts=3)
        env = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert [i.number for i in env.items] == [42]

    @respx.mock
    async def test_secondary_rate_limit_honours_retry_after(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=[
                # 403 WITHOUT remaining=0 plus Retry-After is the secondary limit: retryable
                httpx.Response(403, json={"message": "secondary"}, headers={"retry-after": "1"}),
                httpx.Response(200, json=[ISSUE]),
            ]
        )
        provider = make_provider(max_attempts=3)
        env = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert [i.number for i in env.items] == [42]

    @respx.mock
    async def test_tls_failure_suggests_the_os_trust_store(self):
        """A bare CERTIFICATE_VERIFY_FAILED is unactionable; the hint names the fix."""
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
            )
        )
        provider = make_provider(max_attempts=1)
        with pytest.raises(UpstreamError, match="SSL_TRUST_STORE=system"):
            await provider.list_issues(ListIssuesQuery())
        await provider.aclose()

    @respx.mock
    async def test_no_trust_store_hint_when_already_using_the_os_store(self):
        respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
            )
        )
        provider = make_provider(max_attempts=1, ssl_trust="system")
        with pytest.raises(UpstreamError) as exc:
            await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert "SSL_TRUST_STORE" not in str(exc.value)

    @respx.mock
    async def test_connection_error_is_retried_then_wrapped(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=httpx.ConnectError("no route to host")
        )
        provider = make_provider(max_attempts=2)
        with pytest.raises(UpstreamError):
            await provider.list_issues(ListIssuesQuery())
        await provider.aclose()
        assert route.call_count == 2


class TestEtagCache:
    @respx.mock
    async def test_304_reuses_the_cached_payload(self):
        route = respx.get(f"{BASE}/repos/{REPO}/issues").mock(
            side_effect=[
                httpx.Response(200, json=[ISSUE], headers={"etag": 'W/"abc"'}),
                httpx.Response(304),
            ]
        )
        provider = make_provider()
        first = await provider.list_issues(ListIssuesQuery())
        second = await provider.list_issues(ListIssuesQuery())
        await provider.aclose()

        assert [i.number for i in first.items] == [i.number for i in second.items] == [42]
        assert route.call_count == 2
        assert route.calls[1].request.headers["if-none-match"] == 'W/"abc"'

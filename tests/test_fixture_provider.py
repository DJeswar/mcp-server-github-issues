"""Fixture provider behaviour: filtering, sorting, pagination, PR exclusion, errors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.errors import NotFoundError
from server.models import (
    GetIssueQuery,
    ListIssuesQuery,
    ListLabelsQuery,
    ListMilestonesQuery,
    SearchIssuesQuery,
)

PR_NUMBER = 13


def numbers(env) -> list[int]:
    return [item.number for item in env.items]


class TestEnvelope:
    async def test_records_backend_and_repo(self, provider):
        env = await provider.list_issues(ListIssuesQuery())
        assert env.backend == "fixture"
        assert env.repo == "example/issues-demo"

    async def test_fetched_at_is_fixture_now_not_wall_clock(self, provider):
        env = await provider.list_issues(ListIssuesQuery())
        assert env.fetched_at == datetime(2026, 8, 1, tzinfo=timezone.utc)

    async def test_count_is_page_size(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=5))
        assert env.count == len(env.items) == 5


class TestPullRequestExclusion:
    async def test_pr_absent_from_list(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=100))
        assert PR_NUMBER not in numbers(env)

    async def test_pr_absent_from_search(self, provider):
        # the PR body contains "pull request"; searching for it must still return no PR
        env = await provider.search_issues(SearchIssuesQuery(query="httpx vendored retry"))
        assert PR_NUMBER not in numbers(env)

    async def test_get_issue_on_a_pr_says_it_is_a_pr(self, provider):
        with pytest.raises(NotFoundError, match="is a pull request"):
            await provider.get_issue(GetIssueQuery(number=PR_NUMBER))

    async def test_note_only_counts_prs_that_matched(self, provider):
        """A filter no PR matches must not claim a PR was excluded."""
        env = await provider.list_issues(
            ListIssuesQuery(state="open", labels=["blocked"], milestone="v2")
        )
        assert not any("pull request" in note for note in env.notes)

    async def test_note_reports_pr_when_it_did_match(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=100))
        assert any("1 pull request(s)" in note for note in env.notes)


class TestFiltering:
    async def test_default_state_is_open(self, provider):
        env = await provider.list_issues(ListIssuesQuery(limit=100))
        assert all(item.state == "open" for item in env.items)

    async def test_state_closed(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="closed", limit=100))
        assert sorted(numbers(env)) == [1, 9]

    async def test_labels_use_and_semantics(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", labels=["bug", "blocked"], limit=100)
        )
        assert sorted(numbers(env)) == [3, 8]

    async def test_label_match_is_case_insensitive(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", labels=["BLOCKED"]))
        assert sorted(numbers(env)) == [3, 5, 8]

    async def test_assignee_by_login(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", assignee="alice", limit=100)
        )
        assert sorted(numbers(env)) == [1, 3, 8]

    async def test_assignee_none_means_unassigned(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", assignee="none", limit=100)
        )
        assert sorted(numbers(env)) == [4, 7, 11]

    async def test_assignee_star_means_any(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", assignee="*", limit=100))
        assert 4 not in numbers(env) and 3 in numbers(env)

    async def test_milestone_by_title(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", milestone="v2", limit=100)
        )
        assert sorted(numbers(env)) == [2, 3, 4, 5, 7, 8, 12]

    async def test_milestone_by_number_matches_title(self, provider):
        by_title = await provider.list_issues(ListIssuesQuery(state="all", milestone="v2"))
        by_number = await provider.list_issues(ListIssuesQuery(state="all", milestone="2"))
        assert numbers(by_title) == numbers(by_number)

    async def test_milestone_none(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", milestone="none", limit=100)
        )
        assert sorted(numbers(env)) == [6, 10, 11]

    async def test_since_filters_on_updated_at(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(
                state="all", since=datetime(2026, 7, 29, tzinfo=timezone.utc), limit=100
            )
        )
        assert sorted(numbers(env)) == [5, 6, 10]


class TestSorting:
    async def test_created_desc_is_the_default(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=100))
        created = [item.created_at for item in env.items]
        assert created == sorted(created, reverse=True)

    async def test_updated_asc(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", sort="updated", direction="asc", limit=100)
        )
        updated = [item.updated_at for item in env.items]
        assert updated == sorted(updated)

    async def test_comments_desc_puts_most_discussed_first(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="all", sort="comments", direction="desc", limit=100)
        )
        assert env.items[0].comments == 2


class TestPagination:
    async def test_has_more_and_next_page(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=5, page=1))
        assert env.has_more is True
        assert env.next_page == 2

    async def test_last_page_reports_no_more(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=5, page=3))
        assert env.has_more is False
        assert env.next_page is None

    async def test_pages_do_not_overlap_and_cover_everything(self, provider):
        seen: list[int] = []
        for page in (1, 2, 3):
            env = await provider.list_issues(
                ListIssuesQuery(state="all", limit=5, page=page)
            )
            seen.extend(numbers(env))
        assert len(seen) == len(set(seen)) == 12  # 13 rows minus the pull request

    async def test_page_beyond_the_end_is_empty_not_an_error(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=5, page=99))
        assert env.items == [] and env.has_more is False


class TestGetIssue:
    async def test_returns_body_and_comments(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=3))
        detail = env.items[0]
        assert detail.number == 3
        assert "x-ratelimit-remaining" in detail.body
        assert len(detail.comment_list) == 2

    async def test_parses_cross_references(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=3))
        assert env.items[0].references == [5]

    async def test_include_comments_false_omits_them(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=3, include_comments=False))
        assert env.items[0].comment_list == []
        assert any("include_comments=false" in note for note in env.notes)

    async def test_comment_limit_is_reported_not_silent(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=3, comment_limit=1))
        assert len(env.items[0].comment_list) == 1
        assert any("not returned" in note for note in env.notes)

    async def test_body_truncation_is_flagged(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=3, max_body_chars=100))
        detail = env.items[0]
        assert detail.body_truncated is True
        assert len(detail.body) == 100
        assert any("truncated" in note for note in env.notes)

    async def test_references_survive_truncation(self, provider):
        """#5 is mentioned late in #3's body; truncation must not hide the dependency."""
        env = await provider.get_issue(GetIssueQuery(number=3, max_body_chars=100))
        assert env.items[0].references == [5]

    async def test_untrusted_warning_always_present(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=1))
        assert any("untrusted" in note for note in env.notes)

    async def test_missing_issue_raises_not_found(self, provider):
        with pytest.raises(NotFoundError, match="does not exist"):
            await provider.get_issue(GetIssueQuery(number=9999))


class TestSearch:
    async def test_finds_by_title_terms(self, provider):
        env = await provider.search_issues(SearchIssuesQuery(query="rate limit"))
        assert 3 in numbers(env)

    async def test_title_outranks_body(self, provider):
        env = await provider.search_issues(SearchIssuesQuery(query="pagination"))
        assert env.items[0].number == 2

    async def test_state_filter_applies(self, provider):
        env = await provider.search_issues(
            SearchIssuesQuery(query="error messages", state="open")
        )
        assert 9 not in numbers(env)

    async def test_no_match_is_empty_not_an_error(self, provider):
        env = await provider.search_issues(SearchIssuesQuery(query="zzzznotpresent"))
        assert env.items == []

    async def test_ranking_approximation_is_declared(self, provider):
        env = await provider.search_issues(SearchIssuesQuery(query="rate"))
        assert any("approximation" in note for note in env.notes)


class TestLabelsAndMilestones:
    async def test_labels(self, provider):
        env = await provider.list_labels(ListLabelsQuery())
        assert [item.name for item in env.items] == [
            "bug",
            "enhancement",
            "blocked",
            "docs",
            "security",
            "needs-triage",
        ]

    async def test_planted_label_description_is_returned_intact(self, provider):
        """The third injection vector: a payload in a label description, via list_labels."""
        env = await provider.list_labels(ListLabelsQuery())
        planted = next(i for i in env.items if i.name == "needs-triage")
        assert "ignore previous instructions" in (planted.description or "").lower()

    async def test_default_milestone_state_is_open(self, provider):
        env = await provider.list_milestones(ListMilestonesQuery())
        assert [item.title for item in env.items] == ["v2"]

    async def test_milestone_state_all_sorted_by_due_date(self, provider):
        env = await provider.list_milestones(ListMilestonesQuery(state="all"))
        assert [item.title for item in env.items] == ["v1.0", "v2"]

    async def test_milestone_counts_are_exposed(self, provider):
        env = await provider.list_milestones(ListMilestonesQuery(state="open"))
        assert env.items[0].open_issues == 7


class TestWorkedExample:
    """The runbook's own multi-step question, which the corpus is shaped to answer."""

    async def test_blocked_open_issues_on_the_next_release(self, provider):
        env = await provider.list_issues(
            ListIssuesQuery(state="open", labels=["blocked"], milestone="v2")
        )
        assert numbers(env) == [5, 3, 8]  # created desc

        by_number = {item.number: item for item in env.items}
        assert by_number[5].assignees == ["carol"]
        assert by_number[3].assignees == ["alice"]
        assert by_number[8].assignees == ["alice"]

        stale = sorted(n for n, i in by_number.items() if i.days_since_update > 7)
        assert stale == [3, 8]

    async def test_days_since_update_matches_the_documented_values(self, provider):
        env = await provider.list_issues(ListIssuesQuery(state="all", limit=100))
        actual = {item.number: item.days_since_update for item in env.items}
        expected = {
            1: 51.67, 2: 3.59, 3: 26.31, 4: 11.42, 5: 1.58, 6: 0.5,
            7: 16.61, 8: 36.53, 9: 62.31, 10: 2.65, 11: 43.62, 12: 5.37,
        }
        assert actual == expected


class TestPlantedInjections:
    """Phase 4c/5 depend on these payloads existing and reaching the tool output."""

    async def test_direct_injection_in_issue_body(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=7))
        assert "ignore previous instructions" in env.items[0].body.lower()

    async def test_exfiltration_injection_in_a_comment(self, provider):
        env = await provider.get_issue(GetIssueQuery(number=12))
        bodies = " ".join(c.body.lower() for c in env.items[0].comment_list)
        assert "issue-telemetry.example.net" in bodies
        assert "groq_api_key" in bodies

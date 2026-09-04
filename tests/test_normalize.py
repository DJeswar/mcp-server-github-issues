from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.normalize import (
    days_between,
    is_pull_request,
    parse_dt,
    parse_references,
    truncate,
)


class TestTruncate:
    def test_short_text_untouched(self):
        assert truncate("hello", 100) == ("hello", False)

    def test_none_becomes_empty(self):
        assert truncate(None, 100) == ("", False)

    def test_exactly_at_limit_is_not_truncated(self):
        assert truncate("abcde", 5) == ("abcde", False)

    def test_over_limit_is_cut_and_flagged(self):
        text, cut = truncate("abcdef", 5)
        assert (text, cut) == ("abcde", True)


class TestParseReferences:
    def test_finds_and_dedupes_in_first_appearance_order(self):
        assert parse_references("blocked by #5, see #3, again #5") == [5, 3]

    def test_ignores_mid_word_and_path_hashes(self):
        # `abc#1` is not a reference; neither is a URL fragment like /issues#9
        assert parse_references("abc#1 and https://x/issues#9") == []

    def test_no_references(self):
        assert parse_references("nothing here") == []

    def test_none_body(self):
        assert parse_references(None) == []


class TestParseDt:
    def test_z_suffix_becomes_utc_aware(self):
        assert parse_dt("2026-08-01T00:00:00Z") == datetime(2026, 8, 1, tzinfo=timezone.utc)

    def test_naive_is_assumed_utc(self):
        assert parse_dt("2026-08-01T00:00:00").tzinfo is timezone.utc

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_is_none(self, empty):
        assert parse_dt(empty) is None


def test_days_between_is_fractional():
    later = datetime(2026, 8, 1, tzinfo=timezone.utc)
    earlier = datetime(2026, 7, 30, 10, 5, tzinfo=timezone.utc)
    assert days_between(later, earlier) == 1.58


class TestIsPullRequest:
    def test_true_when_pull_request_key_present(self):
        assert is_pull_request({"number": 1, "pull_request": {"url": "..."}}) is True

    def test_false_for_plain_issue(self):
        assert is_pull_request({"number": 1}) is False

    def test_false_when_key_is_empty(self):
        assert is_pull_request({"number": 1, "pull_request": None}) is False

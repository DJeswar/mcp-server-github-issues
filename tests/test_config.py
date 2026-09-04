"""Settings resolution. Bad config must fail at startup, not mid-conversation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.config import load_settings
from server.errors import ConfigError


class TestDefaults:
    def test_empty_env_gives_the_fixture_backend(self):
        s = load_settings({})
        assert s.backend == "fixture"
        assert s.github_token is None
        assert s.ssl_trust == "certifi"

    def test_default_fixture_now(self):
        assert load_settings({}).fixture_now == datetime(2026, 8, 1, tzinfo=timezone.utc)

    def test_fixture_dir_exists(self):
        assert (load_settings({}).fixture_dir / "issues.json").is_file()


class TestBackend:
    def test_unknown_backend_is_rejected(self):
        with pytest.raises(ConfigError, match="ISSUES_BACKEND"):
            load_settings({"ISSUES_BACKEND": "postgres"})

    def test_github_backend_requires_a_repo(self):
        with pytest.raises(ConfigError, match="requires GITHUB_REPO"):
            load_settings({"ISSUES_BACKEND": "github"})

    @pytest.mark.parametrize("bad", ["ownerrepo", "owner/", "/repo", "a/b/c"])
    def test_malformed_repo_is_rejected(self, bad):
        with pytest.raises(ConfigError, match="owner/name"):
            load_settings({"ISSUES_BACKEND": "github", "GITHUB_REPO": bad})

    def test_valid_github_config(self):
        s = load_settings({"ISSUES_BACKEND": "github", "GITHUB_REPO": "octo/demo"})
        assert (s.backend, s.github_repo) == ("github", "octo/demo")

    def test_backend_is_case_insensitive(self):
        assert load_settings({"ISSUES_BACKEND": "FIXTURE"}).backend == "fixture"


class TestToken:
    def test_blank_token_is_treated_as_absent(self):
        """Unauthenticated public reads are a supported mode, not a misconfiguration."""
        s = load_settings({"ISSUES_BACKEND": "github", "GITHUB_REPO": "o/r", "GITHUB_TOKEN": "  "})
        assert s.github_token is None

    def test_token_is_read_when_present(self):
        s = load_settings(
            {"ISSUES_BACKEND": "github", "GITHUB_REPO": "o/r", "GITHUB_TOKEN": "ghp_x"}
        )
        assert s.github_token == "ghp_x"

    def test_token_is_not_exposed_by_settings_repr(self):
        s = load_settings(
            {
                "ISSUES_BACKEND": "github",
                "GITHUB_REPO": "o/r",
                "GITHUB_TOKEN": "ghp_never_print_this",
            }
        )
        assert "ghp_never_print_this" not in repr(s)


class TestFixtureNow:
    def test_z_suffix_is_accepted(self):
        s = load_settings({"FIXTURE_NOW": "2026-01-02T03:04:05Z"})
        assert s.fixture_now == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_naive_datetime_is_assumed_utc(self):
        assert load_settings({"FIXTURE_NOW": "2026-01-02T00:00:00"}).fixture_now.tzinfo is (
            timezone.utc
        )

    def test_garbage_is_rejected_by_name(self):
        with pytest.raises(ConfigError, match="FIXTURE_NOW"):
            load_settings({"FIXTURE_NOW": "last tuesday"})


class TestSslTrust:
    def test_system_is_accepted(self):
        assert load_settings({"SSL_TRUST_STORE": "system"}).ssl_trust == "system"

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ConfigError, match="SSL_TRUST_STORE"):
            load_settings({"SSL_TRUST_STORE": "windows"})

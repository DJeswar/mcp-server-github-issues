"""Data providers. `make_provider()` is the only thing the server layer needs."""

from __future__ import annotations

from ..config import Settings
from .base import IssuesProvider


def make_provider(settings: Settings) -> IssuesProvider:
    """Select the backend. Imports are local so the fixture path never needs httpx."""
    if settings.backend == "github":
        from .github import GitHubProvider

        return GitHubProvider(
            repo=settings.github_repo or "",
            token=settings.github_token,
            ssl_trust=settings.ssl_trust,
        )

    from .fixture import FixtureProvider

    return FixtureProvider(
        fixture_dir=settings.fixture_dir,
        now=settings.fixture_now,
    )


__all__ = ["IssuesProvider", "make_provider"]

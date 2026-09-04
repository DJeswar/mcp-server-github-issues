from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.config import FIXTURE_DIR, load_settings
from server.main import build_server
from server.providers.fixture import FixtureProvider

FIXTURE_NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


@pytest.fixture
def tmp_dir():
    """A scratch directory. Deliberately NOT pytest's `tmp_path`.

    pytest's temp machinery fails on this machine either way -- see the note in pyproject.toml.
    Requesting `tmp_path` even once makes the whole session's teardown raise
    PermissionError [WinError 5], so the suite avoids it entirely and cleans up its own directory.
    """
    with tempfile.TemporaryDirectory(prefix="mcpagent-") as path:
        yield Path(path)


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider(fixture_dir=FIXTURE_DIR, now=FIXTURE_NOW)


@pytest.fixture
def server():
    """Server wired to the fixture backend, with env explicitly empty.

    Passing `{}` rather than reading os.environ matters: a developer with ISSUES_BACKEND=github
    in their shell would otherwise silently run the whole suite against live GitHub.
    """
    return build_server(load_settings({}))

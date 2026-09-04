"""Environment-driven settings, resolved once at startup.

Invalid configuration raises ConfigError here rather than surfacing later as a confusing tool
failure -- a missing GITHUB_REPO should be a startup message, not a mystery 404 mid-conversation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from .errors import ConfigError

Backend = Literal["fixture", "github"]
SslTrust = Literal["certifi", "system"]

DEFAULT_FIXTURE_NOW = "2026-08-01T00:00:00Z"
FIXTURE_DIR = Path(__file__).parent / "fixtures"

#: `FIXTURE_DIR` may be overridden so a caller can point at a different corpus. The eval suite
#: uses it for the "empty repository" edge case, which is otherwise unreachable: an agent that
#: answers well on a populated repo can still fall apart when there is nothing to find.


def _parse_dt(raw: str, var: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{var} is not a valid ISO-8601 datetime: {raw!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Settings:
    backend: Backend
    github_repo: str | None
    github_token: str | None = field(repr=False)
    fixture_now: datetime
    fixture_dir: Path
    ssl_trust: SslTrust = "certifi"

    # Deliberately no `repo_label` here: the provider owns that string (the fixture backend
    # reads it from repo.json), and a second copy in Settings drifts from the envelope.


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Read settings from `env` (defaults to os.environ, after loading a local .env)."""
    if env is None:
        load_dotenv()  # no-op when there is no .env; never overrides real env vars
        env = dict(os.environ)

    backend = (env.get("ISSUES_BACKEND") or "fixture").strip().lower()
    if backend not in ("fixture", "github"):
        raise ConfigError(
            f"ISSUES_BACKEND must be 'fixture' or 'github', got {backend!r}"
        )

    repo = (env.get("GITHUB_REPO") or "").strip() or None
    if backend == "github":
        if not repo:
            raise ConfigError("ISSUES_BACKEND=github requires GITHUB_REPO ('owner/name')")
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise ConfigError(f"GITHUB_REPO must be 'owner/name', got {repo!r}")

    # Empty string is treated as absent: unauthenticated public reads are a supported mode
    # (60 req/hr), which is what makes the live path testable without an account.
    token = (env.get("GITHUB_TOKEN") or "").strip() or None

    fixture_now = _parse_dt(
        (env.get("FIXTURE_NOW") or DEFAULT_FIXTURE_NOW).strip(), "FIXTURE_NOW"
    )

    # 'system' trusts the OS certificate store instead of certifi's bundle. Needed behind a
    # TLS-inspecting corporate proxy, which re-signs certificates with an internal CA that
    # certifi does not carry. Opt-in rather than default: silently changing which CAs are
    # trusted is not something configuration should do behind your back.
    ssl_trust = (env.get("SSL_TRUST_STORE") or "certifi").strip().lower()
    if ssl_trust not in ("certifi", "system"):
        raise ConfigError(
            f"SSL_TRUST_STORE must be 'certifi' or 'system', got {ssl_trust!r}"
        )

    fixture_dir = (env.get("FIXTURE_DIR") or "").strip()
    resolved_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
    if backend == "fixture" and not resolved_dir.is_dir():
        raise ConfigError(f"FIXTURE_DIR is not a directory: {resolved_dir}")

    return Settings(
        backend=backend,  # type: ignore[arg-type]
        github_repo=repo,
        github_token=token,
        fixture_now=fixture_now,
        fixture_dir=resolved_dir,
        ssl_trust=ssl_trust,  # type: ignore[arg-type]
    )

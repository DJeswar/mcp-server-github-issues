"""Entrypoint: `python -m server.main` (stdio transport).

Inspect it with:
    npx @modelcontextprotocol/inspector .venv\\Scripts\\python.exe -m server.main
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import Settings, load_settings
from .errors import ConfigError, IssuesError
from .providers import make_provider
from .providers.base import IssuesProvider
from .tools import SERVER_INSTRUCTIONS, register_tools


def build_server(
    settings: Settings | None = None, provider: IssuesProvider | None = None
) -> MCPServer:
    """Wire settings -> provider -> tools. Used by main() and by the tests."""
    settings = settings or load_settings()
    provider = provider or make_provider(settings)

    srv = MCPServer(
        name="github-issues",
        title="GitHub Issues (read-only)",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
    )
    register_tools(srv, provider)
    return srv


def main() -> int:
    try:
        settings = load_settings()
        provider = make_provider(settings)
        # the provider owns the repo label, so the banner cannot disagree with the envelope
        repo = provider.repo_label
    except (ConfigError, IssuesError) as exc:
        # stderr, not stdout: stdout is the JSON-RPC channel
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(
        f"github-issues MCP server {__version__} | backend={settings.backend} | repo={repo}",
        file=sys.stderr,
    )
    build_server(settings, provider).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

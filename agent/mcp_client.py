"""Toolset: how the agent reaches the MCP server.

Two implementations, for the same reason the server has two data providers.

- `StdioToolset` spawns `python -m server.main` and speaks real JSON-RPC. This is the honest
  architecture -- the agent is an MCP client, not a caller of internal functions -- and it is
  what proves the published server works.
- `InProcessToolset` calls the same tool handlers directly. Identical semantics (same handlers,
  same schemas, same errors), without a subprocess per test. Node and graph tests use it; the
  end-to-end test uses stdio, so the transport is still covered.
"""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Protocol

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from server.config import load_settings
from server.main import build_server

from .models.base import ToolSpec

#: Env vars forwarded to a spawned server. Anything else is deliberately not inherited, so a
#: stray ISSUES_BACKEND=github in the parent shell cannot silently point tests at live GitHub.
_FORWARDED = ("ISSUES_BACKEND", "GITHUB_REPO", "GITHUB_TOKEN", "FIXTURE_NOW", "SSL_TRUST_STORE")


class ToolResult(BaseModel):
    ok: bool
    envelope: dict[str, Any] | None = None
    error: str | None = None


class Toolset(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call(self, name: str, args: dict[str, Any]) -> ToolResult: ...
    async def aclose(self) -> None: ...


def _error_text(result: Any) -> str:
    parts = [
        getattr(block, "text", "") for block in getattr(result, "content", []) or []
    ]
    return " ".join(p for p in parts if p) or "tool reported an error with no message"


class InProcessToolset:
    """Same handlers, no subprocess."""

    def __init__(self, server: Any | None = None, env: dict[str, str] | None = None) -> None:
        # env defaults to {} rather than os.environ: tests must not be steered by the shell
        self._srv = server or build_server(load_settings(env if env is not None else {}))

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema or {},
            )
            for tool in await self._srv.list_tools()
        ]

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self._srv.call_tool(name, args)
        except ToolError as exc:
            # anticipated tool failures (not found, bad args, rate limit) carry their message
            return ToolResult(ok=False, error=str(exc))
        if getattr(result, "is_error", False):
            return ToolResult(ok=False, error=_error_text(result))
        return ToolResult(ok=True, envelope=result.structured_content or {})

    async def aclose(self) -> None:
        return None


class StdioToolset:
    """Spawns the server as a subprocess and speaks the real protocol.

    **Must be used as an async context manager, inside a single task:**

        async with StdioToolset() as toolset:
            ...

    The MCP stdio client is built on anyio task groups, and anyio requires a cancel scope to be
    exited by the same task that entered it. Splitting `open()` and `aclose()` across tasks -- a
    yielding pytest fixture, for instance -- raises "Attempted to exit cancel scope in a
    different task", which points nowhere near the actual mistake. `aclose()` therefore checks
    the task itself and says what to do instead.
    """

    def __init__(
        self,
        python: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._python = python or sys.executable
        self._cwd = cwd or str(__import__("pathlib").Path(__file__).resolve().parent.parent)
        source = env if env is not None else os.environ
        self._env = {k: source[k] for k in _FORWARDED if source.get(k)}
        self._env.setdefault("ISSUES_BACKEND", "fixture")
        self._env["PYTHONIOENCODING"] = "utf-8"
        self._stack: AsyncExitStack | None = None
        self._client: Any = None
        self._owner_task: Any = None

    async def open(self) -> StdioToolset:
        import asyncio

        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=self._python, args=["-m", "server.main"], cwd=self._cwd, env=self._env
        )
        self._stack = AsyncExitStack()
        self._client = await self._stack.enter_async_context(Client(params))
        self._owner_task = asyncio.current_task()
        return self

    async def __aenter__(self) -> StdioToolset:
        return await self.open()

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("StdioToolset.open() must be awaited before use")
        return self._client

    async def list_tools(self) -> list[ToolSpec]:
        listing = await self._require_client().list_tools()
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema or {},
            )
            for tool in listing.tools
        ]

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        result = await self._require_client().call_tool(name, args)
        if getattr(result, "is_error", False):
            return ToolResult(ok=False, error=_error_text(result))
        return ToolResult(ok=True, envelope=result.structured_content or {})

    async def aclose(self) -> None:
        import asyncio

        if self._stack is None:
            return
        if self._owner_task is not None and asyncio.current_task() is not self._owner_task:
            raise RuntimeError(
                "StdioToolset must be opened and closed in the same asyncio task, because the "
                "MCP stdio client uses anyio task groups. Use "
                "`async with StdioToolset() as toolset:` inside one coroutine instead of "
                "splitting open()/aclose() across a fixture or task boundary."
            )
        await self._stack.aclose()
        self._stack = None
        self._client = None
        self._owner_task = None

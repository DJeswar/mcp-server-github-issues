"""End-to-end over the real MCP transport.

The other agent tests use InProcessToolset for speed. This one spawns `python -m server.main` and
speaks JSON-RPC, so "the agent is an MCP client" is tested rather than asserted.

Every test opens the toolset with `async with` *inside the test body* rather than via a yielding
fixture. That is not style: the MCP stdio client uses anyio task groups, which must be exited by
the task that entered them, and a yielding fixture tears down in a different task.
"""

from __future__ import annotations

import pytest

from agent.config import load_agent_settings
from agent.mcp_client import StdioToolset
from agent.run import format_trace, run_agent

QUESTION = (
    "What open issues are blocking the next release, who is assigned to them, "
    "and which have been stale for more than a week?"
)
FIXTURE_ENV = {"ISSUES_BACKEND": "fixture"}


class TestStdioTransport:
    async def test_advertises_the_five_tools(self):
        async with StdioToolset(env=FIXTURE_ENV) as toolset:
            names = {t.name for t in await toolset.list_tools()}
        assert names == {
            "list_issues",
            "get_issue",
            "search_issues",
            "list_labels",
            "list_milestones",
        }

    async def test_tool_call_returns_the_envelope(self):
        async with StdioToolset(env=FIXTURE_ENV) as toolset:
            result = await toolset.call("list_labels", {})
        assert result.ok is True
        assert result.envelope["backend"] == "fixture"

    async def test_tool_error_crosses_the_wire_with_its_message(self):
        async with StdioToolset(env=FIXTURE_ENV) as toolset:
            result = await toolset.call("get_issue", {"number": 9999})
        assert result.ok is False
        assert "does not exist" in (result.error or "")

    async def test_schemas_survive_the_wire(self):
        async with StdioToolset(env=FIXTURE_ENV) as toolset:
            tools = {t.name: t for t in await toolset.list_tools()}
        props = tools["list_issues"].input_schema["properties"]
        assert props["state"]["enum"] == ["open", "closed", "all"]
        assert props["limit"]["maximum"] == 100


class TestAgentOverStdio:
    async def test_worked_example_matches_the_in_process_result(self):
        async with StdioToolset(env=FIXTURE_ENV) as toolset:
            state = await run_agent(
                QUESTION, settings=load_agent_settings({}), toolset=toolset
            )

        assert [o.tool for o in state.observations] == ["list_milestones", "list_issues"]
        assert state.observations[1].issue_numbers == [5, 3, 8]
        assert state.terminated_because is None
        assert {c.issue for c in state.citations} == {3, 5, 8}
        assert "26.31" in (state.answer or "")
        assert "PLAN" in format_trace(state)


class TestEnvIsolation:
    def test_only_the_forwarded_vars_are_passed(self):
        toolset = StdioToolset(env={"ISSUES_BACKEND": "github", "GITHUB_REPO": "o/r",
                                    "UNRELATED": "x"})
        assert toolset._env["ISSUES_BACKEND"] == "github"
        assert toolset._env["GITHUB_REPO"] == "o/r"
        assert "UNRELATED" not in toolset._env

    def test_default_backend_is_fixture(self):
        """A stray ISSUES_BACKEND in the ambient shell must not steer a spawned server."""
        assert StdioToolset(env={})._env["ISSUES_BACKEND"] == "fixture"


class TestMisuse:
    async def test_calling_before_open_raises_clearly(self):
        with pytest.raises(RuntimeError, match="open\\(\\) must be awaited"):
            await StdioToolset().list_tools()

    async def test_closing_from_another_task_explains_the_anyio_constraint(self):
        """The raw anyio error points nowhere near the real mistake, so we replace it."""
        import asyncio

        toolset = StdioToolset(env=FIXTURE_ENV)
        await toolset.open()
        try:
            with pytest.raises(RuntimeError, match="same asyncio task"):
                await asyncio.create_task(toolset.aclose())
        finally:
            await toolset.aclose()  # same task as open(), so this succeeds

    async def test_aclose_is_idempotent(self):
        toolset = StdioToolset(env=FIXTURE_ENV)
        await toolset.open()
        await toolset.aclose()
        await toolset.aclose()

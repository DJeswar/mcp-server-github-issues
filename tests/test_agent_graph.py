"""Graph behaviour: routing, budget exhaustion, and the runbook's worked example."""

from __future__ import annotations

import json
import re

import pytest

from agent.config import load_agent_settings
from agent.graph import route_after_plan
from agent.mcp_client import InProcessToolset
from agent.models.base import ModelResponse
from agent.run import format_trace, run_agent
from agent.state import AgentState, PlanStep

ISSUE_REF_RE = re.compile(r"#(\d+)")


class LoopingModel:
    """Always asks for the same tool call. Used to prove the no-progress halt works."""

    name = "looping"

    def __init__(self, tool: str = "list_labels") -> None:
        self._tool = tool
        self.plan_calls = 0

    async def complete(self, messages, tools=None) -> ModelResponse:
        from agent.prompts import is_synthesis_prompt

        if is_synthesis_prompt(messages):
            return ModelResponse(text=json.dumps({"answer": "partial", "citations": []}))
        self.plan_calls += 1
        return ModelResponse(
            text=json.dumps(
                {"action": "call_tool", "tool": self._tool, "args": {}, "why": "again"}
            )
        )


class TestRouting:
    def test_call_tool_routes_to_execute(self):
        state = AgentState(
            question="q",
            next_action=PlanStep(index=0, action="call_tool", tool="list_issues"),
        )
        assert route_after_plan(state) == "execute"

    def test_finish_routes_to_synthesize(self):
        state = AgentState(question="q", next_action=PlanStep(index=0, action="finish"))
        assert route_after_plan(state) == "synthesize"

    def test_missing_action_routes_to_synthesize(self):
        assert route_after_plan(AgentState(question="q")) == "synthesize"


class TestWorkedExample:
    """The runbook's Phase 4a deliverable: a question needing at least two tool calls."""

    QUESTION = (
        "What open issues are blocking the next release, who is assigned to them, "
        "and which have been stale for more than a week?"
    )

    @pytest.fixture
    async def state(self):
        return await run_agent(
            self.QUESTION, settings=load_agent_settings({}), toolset=InProcessToolset()
        )

    async def test_makes_at_least_two_tool_calls(self, state):
        assert state.budget.tool_calls >= 2
        assert [o.tool for o in state.observations] == ["list_milestones", "list_issues"]

    async def test_second_call_depends_on_the_first(self, state):
        """'v2' must come from the milestones observation, not from a hardcoded plan."""
        milestone_titles = [i["title"] for i in state.observations[0].items]
        assert state.observations[1].args["milestone"] in milestone_titles

    async def test_finds_the_right_blocked_issues(self, state):
        assert state.observations[1].issue_numbers == [5, 3, 8]

    async def test_answer_names_assignees_and_staleness(self, state):
        answer = state.answer or ""
        assert "carol" in answer and "alice" in answer
        assert "26.31" in answer and "36.53" in answer
        assert "#3, #8" in answer  # exactly the two stale ones

    async def test_every_issue_mentioned_is_cited(self, state):
        """The cheapest hallucination check available: an uncited claim has no observation."""
        mentioned = {int(n) for n in ISSUE_REF_RE.findall(state.answer or "")}
        cited = {c.issue for c in state.citations}
        assert mentioned <= cited, f"uncited issues in answer: {mentioned - cited}"

    async def test_plan_history_is_a_usable_trace(self, state):
        assert [s.action for s in state.plan_history] == ["call_tool", "call_tool", "finish"]
        assert all(s.why for s in state.plan_history)

    async def test_did_not_terminate_early(self, state):
        assert state.terminated_because is None

    async def test_trace_renders(self, state):
        trace = format_trace(state)
        for section in ("QUESTION:", "PLAN", "TOOL CALLS:", "ANSWER:", "CITATIONS:", "BUDGET:"):
            assert section in trace


class TestDeterminism:
    async def test_same_question_gives_the_same_answer(self):
        settings = load_agent_settings({})
        first = await run_agent("what is blocking the next release?", settings=settings,
                                toolset=InProcessToolset())
        second = await run_agent("what is blocking the next release?", settings=settings,
                                 toolset=InProcessToolset())
        assert first.answer == second.answer
        assert first.citations == second.citations


class TestBudgets:
    async def test_step_budget_produces_a_partial_answer_not_a_crash(self):
        settings = load_agent_settings({"AGENT_MAX_STEPS": "1"})
        state = await run_agent(
            "what is blocking the next release?", settings=settings,
            toolset=InProcessToolset()
        )
        assert "step budget" in (state.terminated_because or "")
        assert state.answer  # still answered
        assert "may be incomplete" in state.answer
        assert state.budget.tool_calls == 1

    async def test_tool_call_budget(self):
        settings = load_agent_settings({"AGENT_MAX_TOOL_CALLS": "1"})
        state = await run_agent(
            "what is blocking the next release?", settings=settings,
            toolset=InProcessToolset()
        )
        assert "tool-call budget" in (state.terminated_because or "")
        assert state.budget.tool_calls == 1

    async def test_no_progress_halts_a_looping_planner(self):
        settings = load_agent_settings({"AGENT_MAX_STEPS": "20"})
        model = LoopingModel()
        state = await run_agent(
            "anything", settings=settings, toolset=InProcessToolset(), model=model
        )
        assert "no progress" in (state.terminated_because or "")
        # halted well before the step budget, which is the point
        assert state.budget.tool_calls <= 4

    async def test_off_allowlist_tool_is_refused_end_to_end(self):
        settings = load_agent_settings({"AGENT_MAX_STEPS": "6"})
        state = await run_agent(
            "anything",
            settings=settings,
            toolset=InProcessToolset(),
            model=LoopingModel(tool="rm_minus_rf"),
        )
        assert any(e.detector == "tool_allowlist" for e in state.guardrail_events)
        assert all(not o.ok for o in state.observations)
        assert state.answer


class TestSingleIssueScenario:
    async def test_references_are_reported_and_cited(self):
        state = await run_agent(
            "what does issue #3 say?",
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
        )
        assert state.observations[0].tool == "get_issue"
        assert "#5" in (state.answer or "")

        mentioned = {int(n) for n in ISSUE_REF_RE.findall(state.answer or "")}
        cited = {c.issue for c in state.citations}
        assert mentioned <= cited

        # the citation for the referenced issue must admit it was not fetched
        ref = next(c for c in state.citations if c.issue == 5)
        assert "not independently retrieved" in ref.claim

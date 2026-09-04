"""Each node in isolation, driven with hand-built state and scripted models."""

from __future__ import annotations

import json

import pytest

from agent.config import load_agent_settings
from agent.mcp_client import InProcessToolset, ToolResult
from agent.models.base import Message, ModelResponse, ToolSpec
from agent.nodes import execute_node, plan_node, synthesize_node
from agent.state import AgentState, Budget, Observation, PlanStep


class ScriptedModel:
    """Returns whatever text it is given, regardless of prompt."""

    name = "scripted"

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.calls: list[list[Message]] = []

    async def complete(self, messages, tools=None) -> ModelResponse:
        self.calls.append(messages)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return ModelResponse(text=text, model=self.name)


class FailingToolset:
    def __init__(self, error: str = "boom") -> None:
        self._error = error

    async def list_tools(self):
        return []

    async def call(self, name, args):
        return ToolResult(ok=False, error=self._error)

    async def aclose(self):
        return None


SETTINGS = load_agent_settings({})
TOOLS = [ToolSpec(name="list_issues", description="d", input_schema={})]


class TestPlanNode:
    async def test_call_tool_is_recorded_with_reasoning(self):
        model = ScriptedModel(
            json.dumps(
                {"action": "call_tool", "tool": "list_issues", "args": {"state": "open"},
                 "why": "because"}
            )
        )
        out = await plan_node(
            AgentState(question="q"), model=model, tools=TOOLS, settings=SETTINGS
        )
        step = out["next_action"]
        assert (step.action, step.tool, step.why) == ("call_tool", "list_issues", "because")
        assert out["plan_history"] == [step]
        assert out["budget"].steps == 1

    async def test_finish_action(self):
        model = ScriptedModel(json.dumps({"action": "finish", "why": "done"}))
        out = await plan_node(
            AgentState(question="q"), model=model, tools=TOOLS, settings=SETTINGS
        )
        assert out["next_action"].action == "finish"
        assert "terminated_because" not in out  # finishing normally is not early termination

    async def test_unparseable_output_finishes_and_records_why(self):
        model = ScriptedModel("I refuse to emit JSON")
        out = await plan_node(
            AgentState(question="q"), model=model, tools=TOOLS, settings=SETTINGS
        )
        assert out["next_action"].action == "finish"
        assert "unparseable" in out["terminated_because"]

    async def test_unknown_action_finishes_and_records_why(self):
        model = ScriptedModel(json.dumps({"action": "launch_missiles"}))
        out = await plan_node(
            AgentState(question="q"), model=model, tools=TOOLS, settings=SETTINGS
        )
        assert out["next_action"].action == "finish"
        assert "unknown action" in out["terminated_because"]

    async def test_non_dict_args_are_coerced_to_empty(self):
        model = ScriptedModel(
            json.dumps({"action": "call_tool", "tool": "list_issues", "args": "nope"})
        )
        out = await plan_node(
            AgentState(question="q"), model=model, tools=TOOLS, settings=SETTINGS
        )
        assert out["next_action"].args == {}

    @pytest.mark.parametrize(
        "budget,fragment",
        [
            (Budget(steps=8), "step budget"),
            (Budget(tool_calls=12), "tool-call budget"),
            (Budget(no_progress=2), "no progress"),
        ],
    )
    async def test_budget_exhaustion_stops_without_calling_the_model(self, budget, fragment):
        model = ScriptedModel(json.dumps({"action": "call_tool", "tool": "list_issues"}))
        out = await plan_node(
            AgentState(question="q", budget=budget),
            model=model,
            tools=TOOLS,
            settings=SETTINGS,
        )
        assert out["next_action"].action == "finish"
        assert fragment in out["terminated_because"]
        assert model.calls == []  # no point paying for a call we will not use

    async def test_wall_clock_budget(self):
        settings = load_agent_settings({"AGENT_MAX_WALL_CLOCK": "0.0001"})
        model = ScriptedModel(json.dumps({"action": "finish"}))
        state = AgentState(question="q", budget=Budget(started_at=1.0))
        out = await plan_node(state, model=model, tools=TOOLS, settings=settings)
        assert "wall-clock budget" in out["terminated_because"]


class TestExecuteNode:
    async def test_successful_call_records_the_envelope(self):
        state = AgentState(
            question="q",
            next_action=PlanStep(
                index=0, action="call_tool", tool="list_labels", args={}
            ),
        )
        out = await execute_node(state, toolset=InProcessToolset())
        obs = out["observations"][0]
        assert obs.ok is True
        assert obs.envelope["backend"] == "fixture"
        assert [i["name"] for i in obs.items][0] == "bug"
        assert out["budget"].tool_calls == 1
        assert out["budget"].no_progress == 0

    async def test_off_allowlist_tool_is_refused_and_counted(self):
        state = AgentState(
            question="q",
            next_action=PlanStep(index=0, action="call_tool", tool="delete_repo", args={}),
        )
        out = await execute_node(state, toolset=InProcessToolset())
        assert out["observations"][0].ok is False
        assert "not available" in out["observations"][0].error
        event = out["guardrail_events"][0]
        assert (event.detector, event.action) == ("tool_allowlist", "refused")
        assert out["budget"].tool_calls == 0  # a refused call costs no tool budget

    async def test_tool_error_marks_no_progress(self):
        state = AgentState(
            question="q",
            next_action=PlanStep(index=0, action="call_tool", tool="get_issue",
                                 args={"number": 9999}),
        )
        out = await execute_node(state, toolset=InProcessToolset())
        assert out["observations"][0].ok is False
        assert "does not exist" in out["observations"][0].error
        assert out["budget"].no_progress == 1

    async def test_repeating_a_call_marks_no_progress(self):
        prior = Observation(step=0, tool="list_labels", args={}, ok=True, envelope={"items": []})
        state = AgentState(
            question="q",
            observations=[prior],
            next_action=PlanStep(index=1, action="call_tool", tool="list_labels", args={}),
        )
        out = await execute_node(state, toolset=InProcessToolset())
        assert out["budget"].no_progress == 1

    async def test_no_progress_resets_after_a_useful_call(self):
        state = AgentState(
            question="q",
            budget=Budget(no_progress=1),
            next_action=PlanStep(index=0, action="call_tool", tool="list_labels", args={}),
        )
        out = await execute_node(state, toolset=InProcessToolset())
        assert out["budget"].no_progress == 0

    async def test_missing_next_action_is_handled_not_crashed(self):
        out = await execute_node(AgentState(question="q"), toolset=InProcessToolset())
        assert out["observations"][0].ok is False


class TestSynthesizeNode:
    async def test_answer_and_citations_parsed(self):
        model = ScriptedModel(
            json.dumps(
                {"answer": "Issue #3 is blocked.",
                 "citations": [{"issue": 3, "claim": "blocked"}]}
            )
        )
        out = await synthesize_node(AgentState(question="q"), model=model)
        assert out["answer"] == "Issue #3 is blocked."
        assert out["citations"][0].issue == 3

    async def test_malformed_citations_are_dropped_not_fatal(self):
        model = ScriptedModel(
            json.dumps(
                {
                    "answer": "x",
                    "citations": [
                        {"issue": "three", "claim": "bad"},
                        "not a dict",
                        {"issue": True, "claim": "bool is not an issue number"},
                        {"issue": 4, "claim": "good"},
                    ],
                }
            )
        )
        out = await synthesize_node(AgentState(question="q"), model=model)
        assert [c.issue for c in out["citations"]] == [4]

    async def test_unparseable_output_refuses_to_guess(self):
        model = ScriptedModel("nonsense")
        state = AgentState(
            question="q",
            observations=[Observation(step=0, tool="list_issues", ok=True,
                                      envelope={"items": [{"number": 1}]})],
        )
        out = await synthesize_node(state, model=model)
        assert "could not compose a reliable answer" in out["answer"]
        assert out["citations"] == []

    async def test_early_termination_is_disclosed_in_the_answer(self):
        model = ScriptedModel(json.dumps({"answer": "Partial findings.", "citations": []}))
        state = AgentState(question="q", terminated_because="step budget exhausted")
        out = await synthesize_node(state, model=model)
        assert "may be incomplete" in out["answer"]
        assert "step budget exhausted" in out["answer"]

    async def test_empty_answer_is_replaced(self):
        model = ScriptedModel(json.dumps({"answer": "   ", "citations": []}))
        out = await synthesize_node(AgentState(question="q"), model=model)
        assert out["answer"] == "No answer was produced from the available observations."


class TestToolsetParity:
    async def test_in_process_advertises_the_same_five_tools(self):
        names = {t.name for t in await InProcessToolset().list_tools()}
        assert names == {
            "list_issues",
            "get_issue",
            "search_issues",
            "list_labels",
            "list_milestones",
        }

    async def test_in_process_ignores_the_ambient_shell(self):
        """A stray ISSUES_BACKEND=github in the shell must not point tests at live GitHub."""
        toolset = InProcessToolset()
        result = await toolset.call("list_labels", {})
        assert result.envelope["backend"] == "fixture"

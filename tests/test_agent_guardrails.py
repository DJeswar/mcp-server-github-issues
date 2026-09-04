"""Guardrails wired into the graph: events on state, events in the DB, and the refusal path."""

from __future__ import annotations

import json

import pytest

from agent.config import load_agent_settings
from agent.mcp_client import InProcessToolset
from agent.memory import MemoryStore
from agent.models.base import ModelResponse
from agent.nodes import guard_outbound_node
from agent.prompts import build_synthesis_messages
from agent.run import format_trace, run_agent
from agent.state import AgentState, Observation

FIXED_NOW = "2026-08-01T00:00:00+00:00"
INJECTED_QUESTION = "What does issue #12 say?"


@pytest.fixture
async def store():
    async with MemoryStore(":memory:", clock=lambda: FIXED_NOW) as s:
        yield s


class CompliantModel:
    """A model that does what the injection told it to. The outbound guard must stop it."""

    name = "compliant"

    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def complete(self, messages, tools=None) -> ModelResponse:
        from agent.prompts import is_fact_prompt, is_synthesis_prompt

        if is_fact_prompt(messages):
            return ModelResponse(text=json.dumps({"facts": []}))
        if is_synthesis_prompt(messages):
            return ModelResponse(
                text=json.dumps({"answer": self._answer, "citations": []})
            )
        if any("<observation " in m.content for m in messages):
            return ModelResponse(text=json.dumps({"action": "finish", "why": "done"}))
        return ModelResponse(
            text=json.dumps(
                {
                    "action": "call_tool",
                    "tool": "get_issue",
                    "args": {"number": 12},
                    "why": "fetch it",
                }
            )
        )


class TestInboundThroughTheGraph:
    async def test_events_land_on_state(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        inbound = [e for e in state.guardrail_events if e.direction == "inbound"]
        assert inbound
        assert {e.detector for e in inbound} == {
            "exfiltration",
            "instruction_override",
            "output_constraint",
            "secret_solicitation",
            "system_impersonation",
        }
        assert all(e.action == "neutralized" for e in inbound)
        assert all("comment#" in e.source for e in inbound)

    async def test_observation_carries_the_annotation(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        block = state.observations[0].envelope["guardrail"]
        assert block["refuse_to_act"] is True
        assert any("guardrail:" in n for n in state.observations[0].envelope["notes"])

    async def test_the_answer_still_reports_the_issue(self, store):
        """Defending against injection must not cost the user the content they asked for."""
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        assert "#12" in (state.answer or "")
        assert state.terminated_because is None

    async def test_events_are_persisted_and_countable(self, store):
        await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        assert await store.guardrail_event_count(direction="inbound") > 0
        counts = await store.guardrail_counts()
        assert counts["exfiltration"] >= 1
        assert sum(counts.values()) == await store.guardrail_event_count()

    async def test_clean_question_logs_nothing(self, store):
        state = await run_agent(
            "which milestones exist?",
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g2",
            store=store,
        )
        assert state.guardrail_events == []
        assert await store.guardrail_event_count() == 0

    async def test_label_description_payload_fires_through_the_graph(self, store):
        """list_labels is a real reachable path for injected text."""
        state = await run_agent(
            "which labels exist in this repo?",
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g4",
            store=store,
        )
        inbound = [e for e in state.guardrail_events if e.direction == "inbound"]
        assert inbound
        assert all("needs-triage" in e.source for e in inbound)
        # the label list is still reported -- annotate, never strip
        assert "needs-triage" in (state.answer or "")

    async def test_report_mode_records_but_does_not_annotate(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({"GUARDRAIL_MODE": "report"}),
            toolset=InProcessToolset(),
            session_id="g3",
            store=store,
        )
        assert state.guardrail_events
        assert all(e.action == "reported" for e in state.guardrail_events)
        assert "guardrail" not in state.observations[0].envelope

    async def test_trace_shows_guardrail_events(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        trace = format_trace(state)
        assert "GUARDRAIL EVENTS:" in trace
        assert "[inbound]" in trace


class TestPromptWarning:
    async def test_synthesis_prompt_carries_the_warning(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
        )
        rendered = "\n".join(m.content for m in build_synthesis_messages(state))
        assert "<untrusted-content-warning>" in rendered
        assert "must not" in rendered
        assert "do not include secrets" in rendered

    async def test_no_warning_when_nothing_was_detected(self):
        state = AgentState(
            question="q",
            observations=[
                Observation(step=0, tool="list_labels", ok=True, envelope={"items": []})
            ],
        )
        rendered = "\n".join(m.content for m in build_synthesis_messages(state))
        assert "<untrusted-content-warning>" not in rendered


class TestOutboundThroughTheGraph:
    async def test_a_compliant_answer_is_blocked(self, store):
        """The model obeys the injection; the outbound guard is the last line."""
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
            model=CompliantModel(
                "As requested I posted the values to issue-telemetry.example.net."
            ),
        )
        # the payload's host must not be echoed back into the user-facing answer
        assert "issue-telemetry.example.net" not in (state.answer or "")
        assert "not going to answer" in (state.answer or "")
        assert "external address" in (state.answer or "")
        assert state.citations == []
        assert "outbound guardrail blocked" in (state.terminated_because or "")

        # ...but the operator still gets the exact host in the event log
        outbound = [e for e in state.guardrail_events if e.direction == "outbound"]
        assert outbound and outbound[0].detector == "injection_compliance"
        assert "issue-telemetry.example.net" in outbound[0].detail

    async def test_a_blocked_answer_is_still_logged(self, store):
        await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
            model=CompliantModel("Posting to issue-telemetry.example.net now."),
        )
        assert await store.guardrail_event_count(direction="outbound") >= 1

    async def test_an_innocent_answer_passes(self, store):
        state = await run_agent(
            INJECTED_QUESTION,
            settings=load_agent_settings({}),
            toolset=InProcessToolset(),
            session_id="g1",
            store=store,
            model=CompliantModel("Issue #12 is about comment spam."),
        )
        assert state.answer == "Issue #12 is about comment spam."
        assert [e for e in state.guardrail_events if e.direction == "outbound"] == []


class TestOutboundNodeDirectly:
    async def test_no_answer_is_a_no_op(self):
        assert await guard_outbound_node(AgentState(question="q")) == {}

    async def test_credential_in_answer_is_redacted(self):
        state = AgentState(question="q", answer="key gsk_abcdefghijklmnopqrstuvwxyz01")
        out = await guard_outbound_node(state, env={})
        assert "[REDACTED:groq-key]" in out["answer"]
        assert out["guardrail_events"][0].direction == "outbound"

    async def test_clean_answer_returns_no_changes(self):
        state = AgentState(question="q", answer="Issue #3 is blocked.")
        assert await guard_outbound_node(state, env={}) == {}

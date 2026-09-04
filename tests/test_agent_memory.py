"""Memory wired into the graph: the two-session recall demo, and memory poisoning."""

from __future__ import annotations

import pytest

from agent.config import load_agent_settings
from agent.mcp_client import InProcessToolset
from agent.memory import MemoryStore
from agent.nodes import load_memory_node, persist_node
from agent.run import format_trace, run_agent
from agent.state import AgentState

FIXED_NOW = "2026-08-01T00:00:00+00:00"
SETTINGS = load_agent_settings({})

S1_QUESTION = "Let's plan the release. The v2 milestone is our current priority."
S2_QUESTION = "What should I work on?"


@pytest.fixture
async def store():
    async with MemoryStore(":memory:", clock=lambda: FIXED_NOW) as s:
        yield s


async def ask(question, store, *, session_id, thread_id=None):
    return await run_agent(
        question,
        settings=SETTINGS,
        toolset=InProcessToolset(),
        thread_id=thread_id or session_id,
        session_id=session_id,
        store=store,
    )


class TestTwoSessionRecall:
    """The runbook's Phase 4b deliverable: a fact from session 1 used in session 2."""

    async def test_session_one_writes_the_fact(self, store):
        state = await ask(S1_QUESTION, store, session_id="s1")
        assert [(e.action, e.key, e.value) for e in state.memory_events] == [
            ("written", "priority.milestone", "v2")
        ]
        live = await store.get_live("priority.milestone")
        assert (live.value, live.session_id) == ("v2", "s1")

    async def test_session_two_recalls_and_uses_it(self, store):
        await ask(S1_QUESTION, store, session_id="s1")
        state = await ask(S2_QUESTION, store, session_id="s2")

        # the question names no milestone -- the filter can only have come from memory
        assert "v2" not in S2_QUESTION
        assert [f.key for f in state.recalled_facts] == ["priority.milestone"]
        assert state.observations[0].args["milestone"] == "v2"
        assert state.plan_history[0].why.startswith("You previously said")

    async def test_session_two_discloses_which_fact_it_used(self, store):
        await ask(S1_QUESTION, store, session_id="s1")
        state = await ask(S2_QUESTION, store, session_id="s2")
        assert "Using your remembered priority.milestone = v2" in (state.answer or "")
        assert "The v2 milestone is our current priority" in (state.answer or "")

    async def test_recall_does_not_claim_facts_it_did_not_use(self, store):
        """A priority fact always surfaces; saying it was 'used' when it wasn't is a lie."""
        await ask(S1_QUESTION, store, session_id="s1")
        state = await ask("What does issue #3 say?", store, session_id="s3")
        assert [f.key for f in state.recalled_facts] == ["priority.milestone"]
        assert "Using your remembered" not in (state.answer or "")

    async def test_trace_shows_the_recall(self, store):
        await ask(S1_QUESTION, store, session_id="s1")
        state = await ask(S2_QUESTION, store, session_id="s2")
        trace = format_trace(state)
        assert "RECALLED (long-term memory):" in trace
        assert "session s1" in trace


class TestSupersessionThroughTheGraph:
    async def test_restating_the_priority_supersedes(self, store):
        await ask(S1_QUESTION, store, session_id="s1")
        state = await ask(
            "Actually the v3 milestone is our current priority.", store, session_id="s2"
        )
        assert [e.action for e in state.memory_events] == ["superseded"]
        assert (await store.get_live("priority.milestone")).value == "v3"
        assert len(await store.history("priority.milestone")) == 2

    async def test_later_session_uses_the_new_value(self, store):
        await ask(S1_QUESTION, store, session_id="s1")
        await ask("Actually the v3 milestone is our current priority.", store, session_id="s2")
        state = await ask(S2_QUESTION, store, session_id="s3")
        assert state.observations[0].args["milestone"] == "v3"


class TestMemoryPoisoning:
    """An injection in issue text must never earn a persistent write."""

    async def test_injected_instruction_produces_zero_writes(self, store):
        state = await ask("What does issue #12 say?", store, session_id="s1")

        # the model WAS tempted -- a candidate was proposed and rejected
        rejected = [e for e in state.memory_events if e.action == "rejected"]
        assert rejected, "expected the stub to propose a fact from the injected comment"
        assert await store.count(active_only=False) == 0

    async def test_rejection_names_the_security_gate(self, store):
        state = await ask("What does issue #12 say?", store, session_id="s1")
        rejected = next(e for e in state.memory_events if e.action == "rejected")
        assert any("user_asserted" in g for g in rejected.failed_gates)
        assert "untrusted tool text" in rejected.reason

    async def test_the_issue_text_is_still_reported(self, store):
        """Defending memory must not cost the user the answer they asked for."""
        state = await ask("What does issue #12 say?", store, session_id="s1")
        assert "#12" in (state.answer or "")
        assert state.observations[0].ok is True

    async def test_derivable_fact_is_rejected(self, store):
        state = await ask("Issue #3 has two comments, remember that.", store, session_id="s1")
        rejected = [e for e in state.memory_events if e.action == "rejected"]
        assert rejected
        gates = " ".join(g for e in rejected for g in e.failed_gates)
        assert "not_derivable" in gates or "reusable" in gates
        assert await store.count(active_only=False) == 0


class TestNoStore:
    """Running without long-term memory stays a supported mode."""

    async def test_recall_and_persist_are_no_ops(self):
        state = await run_agent(
            S1_QUESTION, settings=SETTINGS, toolset=InProcessToolset(), store=None
        )
        assert state.recalled_facts == []
        assert state.memory_events == []
        assert state.answer

    async def test_nodes_handle_a_missing_store_directly(self):
        assert await load_memory_node(AgentState(question="q"), store=None) == {}
        from agent.models.stub import StubModel

        assert (
            await persist_node(
                AgentState(question="q"), model=StubModel(), store=None, session_id="s"
            )
            == {}
        )


class TestShortTermMemory:
    """The checkpointer is a different mechanism from the fact store, on purpose."""

    async def test_thread_state_is_persisted_and_resumable(self, tmp_dir):
        from agent.session import open_memory

        settings = load_agent_settings({"MEMORY_DB": ":memory:"})
        async with open_memory(
            settings, checkpoint_db=str(tmp_dir / "ckpt.sqlite3")
        ) as (store, saver):
            await run_agent(
                S1_QUESTION,
                settings=settings,
                toolset=InProcessToolset(),
                thread_id="t1",
                session_id="t1",
                store=store,
                checkpointer=saver,
            )
            tup = await saver.aget_tuple({"configurable": {"thread_id": "t1"}})

            assert tup is not None
            assert tup.checkpoint["channel_values"]["question"] == S1_QUESTION

    async def test_unknown_thread_has_no_checkpoint(self, tmp_dir):
        from agent.session import open_memory

        settings = load_agent_settings({"MEMORY_DB": ":memory:"})
        async with open_memory(
            settings, checkpoint_db=str(tmp_dir / "ckpt.sqlite3")
        ) as (_store, saver):
            assert await saver.aget_tuple({"configurable": {"thread_id": "nope"}}) is None

    async def test_second_turn_resets_execution_state_and_keeps_transcript(self, tmp_dir):
        """A resumed thread must not answer question two from question one's observations."""
        from agent.session import open_memory

        settings = load_agent_settings({"MEMORY_DB": ":memory:"})
        async with open_memory(
            settings, checkpoint_db=str(tmp_dir / "ckpt.sqlite3")
        ) as (store, saver):
            first = await run_agent(
                "What does issue #3 say?",
                settings=settings,
                toolset=InProcessToolset(),
                thread_id="same-thread",
                store=store,
                checkpointer=saver,
            )
            second = await run_agent(
                "Which labels exist in this repo?",
                settings=settings,
                toolset=InProcessToolset(),
                thread_id="same-thread",
                store=store,
                checkpointer=saver,
            )

        assert [o.tool for o in first.observations] == ["get_issue"]
        assert [o.tool for o in second.observations] == ["list_labels"]
        assert second.plan_history[0].index == 0
        assert second.budget.tool_calls == 1
        assert [turn.question for turn in second.conversation] == [
            "What does issue #3 say?",
            "Which labels exist in this repo?",
        ]

    async def test_short_term_can_be_disabled(self, tmp_dir):
        from agent.session import open_memory

        settings = load_agent_settings({"MEMORY_DB": ":memory:"})
        async with open_memory(settings, short_term=False) as (store, saver):
            assert saver is None
            assert await store.count() == 0


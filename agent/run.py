"""Entry point: `run_agent(question)` and a human-readable trace formatter."""

from __future__ import annotations

from typing import Any

from .config import AgentSettings, load_agent_settings
from .graph import build_graph
from .mcp_client import InProcessToolset, Toolset
from .memory import MemoryStore
from .models import make_chat_model
from .models.base import ChatModel
from .state import AgentState


async def run_agent(
    question: str,
    *,
    settings: AgentSettings | None = None,
    toolset: Toolset | None = None,
    model: ChatModel | None = None,
    thread_id: str = "default",
    checkpointer: Any | None = None,
    store: MemoryStore | None = None,
    session_id: str | None = None,
    scope: str = "global",
) -> AgentState:
    """Run one question to completion and return the final state.

    `checkpointer` and `store` stay parameters rather than being constructed here: both are async
    context managers whose lifetime belongs to the caller. Use `open_memory()` from
    `agent.session` for the usual case.
    """
    settings = settings or load_agent_settings()
    model = model or make_chat_model(settings)

    owns_toolset = toolset is None
    toolset = toolset or InProcessToolset()

    try:
        tools = await toolset.list_tools()
        compiled = build_graph(
            model=model,
            toolset=toolset,
            tools=tools,
            settings=settings,
            store=store,
            session_id=session_id or thread_id,
            scope=scope,
        ).compile(checkpointer=checkpointer)

        result = await compiled.ainvoke(
            AgentState(question=question, thread_id=thread_id),
            config={
                # deliberately above our own budgets -- see AgentSettings.recursion_limit
                "recursion_limit": settings.recursion_limit,
                "configurable": {"thread_id": thread_id},
            },
        )
        return AgentState.model_validate(result)
    finally:
        if owns_toolset:
            await toolset.aclose()


def format_trace(state: AgentState) -> str:
    """The plan / tool calls / answer trace the runbook asks for."""
    lines = [f"QUESTION: {state.question}", ""]

    if state.recalled_facts:
        lines.append("RECALLED (long-term memory):")
        for fact in state.recalled_facts:
            quote = f' — you said: "{fact.source_quote}"' if fact.source_quote else ""
            lines.append(
                f"  {fact.key} = {fact.value}{quote}"
                + (f" [session {fact.session_id}, {fact.created_at}]" if fact.created_at else "")
            )
        lines.append("")

    lines.append("PLAN (iterative — one decision per turn, with the reasoning):")
    for step in state.plan_history:
        if step.action == "call_tool":
            lines.append(f"  {step.index}. call {step.tool}({step.args})")
        else:
            lines.append(f"  {step.index}. finish")
        lines.append(f"      why: {step.why}")

    lines.append("")
    lines.append("TOOL CALLS:")
    for obs in state.observations:
        env = obs.envelope or {}
        if obs.ok:
            lines.append(
                f"  step {obs.step}: {obs.tool} -> {len(obs.items)} item(s), "
                f"has_more={env.get('has_more')}, backend={env.get('backend')}"
            )
            for note in env.get("notes") or []:
                lines.append(f"      note: {note}")
        else:
            lines.append(f"  step {obs.step}: {obs.tool} -> ERROR: {obs.error}")

    if state.guardrail_events:
        lines.append("")
        lines.append("GUARDRAIL EVENTS:")
        for event in state.guardrail_events:
            lines.append(
                f"  {event.detector} [{event.direction}] {event.action} "
                f"— {event.source} {event.detail}".rstrip()
            )

    lines.append("")
    lines.append("ANSWER:")
    for line in (state.answer or "(none)").splitlines():
        lines.append(f"  {line}")

    lines.append("")
    lines.append("CITATIONS:")
    for citation in state.citations:
        lines.append(f"  #{citation.issue}: {citation.claim}")

    if state.memory_events:
        lines.append("")
        lines.append("MEMORY WRITE DECISIONS:")
        for event in state.memory_events:
            mark = "+" if event.action in ("written", "superseded") else "-"
            lines.append(f"  {mark} {event.action.upper()} {event.key} = {event.value}")
            lines.append(f"      {event.reason}")

    lines.append("")
    lines.append(
        f"BUDGET: {state.budget.steps} planning turn(s), "
        f"{state.budget.tool_calls} tool call(s), "
        f"no_progress={state.budget.no_progress}"
    )
    if state.terminated_because:
        lines.append(f"TERMINATED EARLY: {state.terminated_because}")

    return "\n".join(lines)

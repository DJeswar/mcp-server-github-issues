"""The planning node: decide the next action, or stop.

Budget enforcement lives here rather than in the conditional edge, because a conditional edge
cannot mutate state -- it can only pick the next node. Deciding "we are out of budget" here means
`terminated_because` is recorded, and synthesis can say plainly that the answer is partial.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import AgentSettings
from ..models.base import ChatModel, ModelOutputError, ToolSpec, parse_json_object
from ..prompts import build_plan_messages
from ..state import AgentState, Budget, PlanStep

log = logging.getLogger("agent.plan")


def _finish(state: AgentState, why: str, *, terminated: str | None = None) -> dict[str, Any]:
    step = PlanStep(index=len(state.plan_history), action="finish", why=why)
    out: dict[str, Any] = {
        "plan_history": [*state.plan_history, step],
        "next_action": step,
    }
    if terminated:
        out["terminated_because"] = terminated
    return out


def _budget_exhausted(state: AgentState, settings: AgentSettings, elapsed: float) -> str | None:
    b = state.budget
    if b.steps >= settings.max_steps:
        return f"step budget exhausted ({b.steps}/{settings.max_steps} planning turns)"
    if b.tool_calls >= settings.max_tool_calls:
        return f"tool-call budget exhausted ({b.tool_calls}/{settings.max_tool_calls})"
    if elapsed >= settings.max_wall_clock:
        return f"wall-clock budget exhausted ({elapsed:.1f}s/{settings.max_wall_clock:.0f}s)"
    if b.no_progress >= settings.no_progress_limit:
        return (
            f"no progress for {b.no_progress} consecutive steps "
            "(the planner repeated itself or the tool kept failing)"
        )
    return None


async def plan_node(
    state: AgentState,
    *,
    model: ChatModel,
    tools: list[ToolSpec],
    settings: AgentSettings,
) -> dict[str, Any]:
    now = time.monotonic()
    started_at = state.budget.started_at or now
    elapsed = now - started_at

    if reason := _budget_exhausted(state, settings, elapsed):
        log.info("planning halted: %s", reason)
        out = _finish(state, "Budget exhausted; answering with what has been gathered.",
                      terminated=reason)
        out["budget"] = state.budget.model_copy(
            update={"started_at": started_at, "elapsed": elapsed}
        )
        return out

    budget = Budget(
        steps=state.budget.steps + 1,
        tool_calls=state.budget.tool_calls,
        no_progress=state.budget.no_progress,
        started_at=started_at,
        elapsed=elapsed,
    )

    response = await model.complete(build_plan_messages(state, tools), tools)

    try:
        payload = parse_json_object(response.text)
    except ModelOutputError as exc:
        log.warning("planner output unusable: %s", exc)
        out = _finish(
            state,
            "The planner returned output that could not be parsed.",
            terminated=f"planner output unparseable: {exc}",
        )
        out["budget"] = budget
        return out

    action = payload.get("action")
    if action == "finish":
        out = _finish(state, str(payload.get("why") or "The observations answer the question."))
        out["budget"] = budget
        return out

    if action != "call_tool":
        out = _finish(
            state,
            f"The planner asked for an unknown action {action!r}.",
            terminated=f"planner returned unknown action {action!r}",
        )
        out["budget"] = budget
        return out

    step = PlanStep(
        index=len(state.plan_history),
        action="call_tool",
        why=str(payload.get("why") or ""),
        tool=payload.get("tool"),
        args=payload.get("args") if isinstance(payload.get("args"), dict) else {},
    )
    log.info("step %d: %s(%s) -- %s", step.index, step.tool, step.args, step.why)
    return {
        "plan_history": [*state.plan_history, step],
        "next_action": step,
        "budget": budget,
    }

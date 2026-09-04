"""The execution node: run exactly one tool call and record the observation."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import ALLOWED_TOOLS
from ..guardrails import annotate
from ..mcp_client import Toolset
from ..state import AgentState, Budget, GuardrailEvent, Observation

log = logging.getLogger("agent.execute")


def _bump(state: AgentState, *, tool_calls: int, no_progress: int) -> Budget:
    started_at = state.budget.started_at or time.monotonic()
    return Budget(
        steps=state.budget.steps,
        tool_calls=tool_calls,
        no_progress=no_progress,
        started_at=started_at,
        elapsed=time.monotonic() - started_at,
    )


async def execute_node(
    state: AgentState, *, toolset: Toolset, mode: str = "enforce"
) -> dict[str, Any]:
    step = state.next_action
    if step is None or step.action != "call_tool" or not step.tool:
        # unreachable via the graph's conditional edge, but a node should not assume its caller
        return {
            "observations": [
                *state.observations,
                Observation(
                    step=len(state.observations),
                    tool="<none>",
                    ok=False,
                    error="execute was reached without a tool call to make",
                )
            ],
            "budget": _bump(
                state,
                tool_calls=state.budget.tool_calls,
                no_progress=state.budget.no_progress + 1,
            ),
        }

    # Allowlist first: a model inventing a tool name must be refused before it reaches the
    # transport, and the refusal must be countable (Phase 5 has a case for exactly this).
    if step.tool not in ALLOWED_TOOLS:
        log.warning("refused off-allowlist tool %r", step.tool)
        return {
            "observations": [
                *state.observations,
                Observation(
                    step=step.index,
                    tool=step.tool,
                    args=step.args,
                    ok=False,
                    error=(
                        f"Tool {step.tool!r} is not available. This server exposes only: "
                        + ", ".join(ALLOWED_TOOLS)
                    ),
                )
            ],
            "guardrail_events": [
                *state.guardrail_events,
                GuardrailEvent(
                    detector="tool_allowlist",
                    direction="outbound",
                    source=f"planner:step{step.index}",
                    action="refused",
                    detail=f"requested tool {step.tool!r}",
                )
            ],
            "budget": _bump(
                state,
                tool_calls=state.budget.tool_calls,
                no_progress=state.budget.no_progress + 1,
            ),
        }

    repeated = any(
        obs.tool == step.tool and obs.args == step.args for obs in state.observations
    )

    result = await toolset.call(step.tool, step.args)

    # Inbound guard runs here rather than in its own node. Scanning before the Observation is
    # built means every later consumer sees the annotated version. Logic lives in
    # guardrails/inbound.py.
    envelope, findings = annotate(result.envelope, step.tool, mode=mode)
    guard_events = [
        GuardrailEvent(
            detector=f.detection.family,
            direction="inbound",
            source=f.path,
            action="neutralized" if mode == "enforce" else "reported",
            span=f.detection.span,
            detail=f.detection.excerpt[:120],
        )
        for f in findings
    ]
    if findings:
        log.warning(
            "inbound guardrail: %d detection(s) in %s -- %s",
            len(findings),
            step.tool,
            ", ".join(sorted({f.detection.family for f in findings})),
        )

    observation = Observation(
        step=step.index,
        tool=step.tool,
        args=step.args,
        ok=result.ok,
        envelope=envelope,
        error=result.error,
    )

    # "No progress" means the planner is going in circles: it asked for something it already has,
    # or the call failed. Either way, repeating it will not help.
    stalled = repeated or not result.ok
    no_progress = state.budget.no_progress + 1 if stalled else 0
    if repeated:
        log.info("step %d repeated an earlier call to %s", step.index, step.tool)

    log.info(
        "step %d: %s -> ok=%s items=%d",
        step.index,
        step.tool,
        result.ok,
        len(observation.items),
    )

    out: dict[str, Any] = {
        "observations": [*state.observations, observation],
        "budget": _bump(
            state, tool_calls=state.budget.tool_calls + 1, no_progress=no_progress
        ),
    }
    if guard_events:
        out["guardrail_events"] = [*state.guardrail_events, *guard_events]
    return out

"""Outbound guard node: the last thing between the answer and the user."""

from __future__ import annotations

import logging
from typing import Any

from ..guardrails import indicators_from_envelopes, scan_outbound
from ..state import AgentState, GuardrailEvent

log = logging.getLogger("agent.guardrails")


async def guard_outbound_node(
    state: AgentState, *, mode: str = "enforce", env: dict[str, str] | None = None
) -> dict[str, Any]:
    if not state.answer:
        return {}

    # Recovered from the annotations the inbound guard left on the observations -- this node runs
    # too late to see the InboundFinding objects themselves.
    signals = indicators_from_envelopes(obs.envelope for obs in state.observations)

    result = scan_outbound(state.answer, indicators=signals, env=env, mode=mode)
    if not result.events:
        return {}

    for event in result.events:
        log.warning(
            "outbound guardrail: detector=%s action=%s %s",
            event.detector,
            event.action,
            event.detail,
        )

    out: dict[str, Any] = {
        "guardrail_events": [
            *state.guardrail_events,
            *[
                GuardrailEvent(
                    detector=event.detector,
                    direction="outbound",
                    source="answer",
                    action=event.action if mode == "enforce" else "reported",
                    detail=event.detail,
                )
                for event in result.events
            ],
        ]
    }

    if result.text != state.answer:
        out["answer"] = result.text
    if result.blocked:
        out["terminated_because"] = (
            "the outbound guardrail blocked the drafted answer: it complied with instructions "
            "found in untrusted repository text"
        )
        # a blocked answer cites nothing -- the citations belonged to the answer we discarded
        out["citations"] = []

    return out

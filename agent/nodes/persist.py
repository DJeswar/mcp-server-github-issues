"""Decide what earns a long-term write.

The node does not decide -- `memory/rules.py` does. This is only the plumbing: ask for candidates,
run every one through the five gates, write the survivors, and record each decision (including
the rejections) so the trace shows the rule working rather than asserting that it does.
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory import Candidate, MemoryStore, evaluate
from ..models.base import ChatModel, ModelOutputError, parse_json_object
from ..prompts import build_fact_messages
from ..state import AgentState, MemoryEvent

log = logging.getLogger("agent.memory")


def _candidate(raw: dict[str, Any], scope: str) -> Candidate | None:
    if not isinstance(raw, dict):
        return None
    key, value = raw.get("key"), raw.get("value")
    if not isinstance(key, str) or not isinstance(value, str) or not key or not value:
        return None
    return Candidate(
        key=key,
        value=value,
        kind=str(raw.get("kind") or ""),
        source_quote=str(raw.get("source_quote") or ""),
        scope=str(raw.get("scope") or scope),
        # `source` is never taken from the model: it is the thing gate 3 checks, and the DB CHECK
        # only accepts user_asserted / user_confirmed anyway.
        source="user_asserted",
    )


async def persist_node(
    state: AgentState,
    *,
    model: ChatModel,
    store: MemoryStore | None,
    session_id: str,
    scope: str = "global",
) -> dict[str, Any]:
    if store is None:
        return {}

    # This node owns every DB write, so the guardrail events land here too rather than giving the
    # guardrail layer its own connection.
    if state.guardrail_events:
        written = await store.log_guardrail_events(
            state.guardrail_events, session_id=session_id
        )
        log.info("logged %d guardrail event(s)", written)

    response = await model.complete(build_fact_messages(state))
    try:
        payload = parse_json_object(response.text)
    except ModelOutputError as exc:
        log.info("no facts extracted: %s", exc)
        return {}

    events: list[MemoryEvent] = []

    for raw in payload.get("facts") or []:
        candidate = _candidate(raw, scope)
        if candidate is None:
            continue

        verdict = evaluate(candidate, user_message=state.question)
        if not verdict.accepted:
            log.info("rejected %s=%s -- %s", candidate.key, candidate.value, verdict.reason)
            events.append(
                MemoryEvent(
                    action="rejected",
                    key=candidate.key,
                    value=candidate.value,
                    reason=verdict.reason,
                    failed_gates=verdict.failed_gates,
                )
            )
            continue

        new_id, superseded_id = await store.write(candidate, session_id=session_id)
        action = "superseded" if superseded_id else "written"
        log.info("%s %s=%s (id=%s)", action, candidate.key, candidate.value, new_id)
        events.append(
            MemoryEvent(
                action=action,
                key=candidate.key,
                value=candidate.value,
                reason=(
                    f"replaced fact id={superseded_id}, retained for audit"
                    if superseded_id
                    else "passed all five gates"
                ),
            )
        )

    return {
        "memory_events": [*state.memory_events, *events]
    } if events else {}

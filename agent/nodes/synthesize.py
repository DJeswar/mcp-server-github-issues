"""The synthesis node: turn observations into a cited answer."""

from __future__ import annotations

import logging
from typing import Any

from ..models.base import ChatModel, ModelOutputError, parse_json_object
from ..prompts import build_synthesis_messages
from ..state import AgentState, Citation

log = logging.getLogger("agent.synthesize")


def _citations(payload: dict[str, Any]) -> list[Citation]:
    out: list[Citation] = []
    for raw in payload.get("citations") or []:
        if not isinstance(raw, dict):
            continue
        issue = raw.get("issue")
        if isinstance(issue, bool) or not isinstance(issue, int):
            continue
        out.append(Citation(issue=issue, claim=str(raw.get("claim") or "")))
    return out


async def synthesize_node(state: AgentState, *, model: ChatModel) -> dict[str, Any]:
    response = await model.complete(build_synthesis_messages(state))

    try:
        payload = parse_json_object(response.text)
    except ModelOutputError as exc:
        log.warning("synthesis output unusable: %s", exc)
        return {
            "answer": (
                "I gathered data but could not compose a reliable answer, so I am not going to "
                "guess. Retrieved: "
                + ", ".join(
                    f"{o.tool} ({len(o.items)} item(s))" for o in state.observations
                )
                + "."
            ),
            "citations": [],
            "terminated_because": state.terminated_because
            or f"synthesis output unparseable: {exc}",
        }

    answer = str(payload.get("answer") or "").strip()
    if not answer:
        answer = "No answer was produced from the available observations."

    if state.terminated_because and "incomplete" not in answer.lower():
        answer += f"\n\nNote: this answer may be incomplete — {state.terminated_because}."

    return {"answer": answer, "citations": _citations(payload)}

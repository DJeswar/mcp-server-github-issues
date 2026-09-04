"""The ChatModel seam.

Design note -- why the planner contract is JSON-in-text rather than native tool calling.

Native provider tool-calling returns a function call but not the *reasoning* behind it, and its
wire format differs across Groq and Gemini. The planner needs `why` for the trace the runbook
asks for, and the stub/replay backends need to emit exactly what a live model emits. A single
JSON contract gives all three: identical across providers, trivially recordable, and it carries
the reasoning. The cost is that we parse and validate JSON ourselves -- `parse_json_object`
below, with a repair pass for fenced output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ModelOutputError(Exception):
    """The model returned something we cannot use. Routed, not crashed."""


class Message(BaseModel):
    role: str  # system | user | assistant
    content: str


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    text: str
    model: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ChatModel(Protocol):
    name: str

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse: ...


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    candidate = text.strip()

    if fenced := _FENCE_RE.match(candidate):
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # last resort: the outermost {...} span. Models like to prepend commentary.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ModelOutputError(f"no JSON object found in model output: {text[:200]!r}")
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ModelOutputError(f"invalid JSON in model output: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ModelOutputError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed

"""Cassette record/replay.

The point is Phase 5: CI should gate on real-model behaviour, but CI must hold no API key and
must not be flaky. Recording once on a machine that has keys, then replaying offline, gives real
model outputs with zero credentials and zero variance.

The seam is built now even though there is nothing to record yet, because retrofitting a record
layer around an already-written graph is much harder than designing it in.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import ChatModel, Message, ModelResponse, ToolSpec


class CassetteMissError(Exception):
    """No recorded response for this exact request."""


def cassette_key(messages: list[Message], tools: list[ToolSpec] | None) -> str:
    """Stable hash of the request. Any prompt change invalidates the cassette, by design."""
    payload = {
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "tools": sorted(t.name for t in (tools or [])),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class ReplayModel:
    """Plays back recorded responses. Never touches the network."""

    name = "replay"

    def __init__(self, cassette_dir: Path) -> None:
        self._dir = Path(cassette_dir)

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        key = cassette_key(messages, tools)
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise CassetteMissError(
                f"no cassette for request {key} (looked in {self._dir}). "
                "Record it on a machine with credentials: "
                "LLM_BACKEND=groq RECORD_CASSETTES=1. Note that any change to the prompt "
                "text changes the key, so cassettes must be re-recorded after prompt edits."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return ModelResponse(**data["response"])


class RecordingModel:
    """Wraps a real model and writes each request/response pair to a cassette."""

    def __init__(self, inner: ChatModel, cassette_dir: Path) -> None:
        self._inner = inner
        self._dir = Path(cassette_dir)
        self.name = f"recording[{inner.name}]"

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        response = await self._inner.complete(messages, tools)
        key = cassette_key(messages, tools)
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{key}.json").write_text(
            json.dumps(
                {
                    "key": key,
                    "request": {
                        "messages": [{"role": m.role, "content": m.content} for m in messages],
                        "tools": sorted(t.name for t in (tools or [])),
                    },
                    "response": response.model_dump(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return response

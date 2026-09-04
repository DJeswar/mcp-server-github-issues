"""Recall long-term facts relevant to this question."""

from __future__ import annotations

import logging
from typing import Any

from ..memory import MemoryStore
from ..state import AgentState, Fact

log = logging.getLogger("agent.memory")


async def load_memory_node(
    state: AgentState,
    *,
    store: MemoryStore | None,
    scope: str = "global",
    limit: int = 5,
) -> dict[str, Any]:
    """No store configured is a supported mode, not an error -- Phase 4a ran without one."""
    if store is None:
        return {}

    facts = await store.recall(question=state.question, scope=scope, limit=limit)
    if facts:
        log.info(
            "recalled %d fact(s): %s",
            len(facts),
            ", ".join(f"{f.key}={f.value}" for f in facts),
        )

    return {
        "recalled_facts": [
            Fact(
                key=f.key,
                value=f.value,
                source_quote=f.source_quote,
                created_at=f.created_at,
                session_id=f.session_id,
            )
            for f in facts
        ]
    }

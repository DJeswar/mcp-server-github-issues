"""Record the completed question and guarded answer in short-term conversation state."""

from __future__ import annotations

from typing import Any

from ..state import AgentState, ConversationTurn


async def complete_turn_node(state: AgentState) -> dict[str, Any]:
    """Append a bounded transcript entry through AgentState's conversation reducer."""
    return {
        "conversation": [
            ConversationTurn(
                question=state.question[:1000],
                answer=(state.answer or "")[:4000],
            )
        ]
    }

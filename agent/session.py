"""Owning the lifetimes of the two memory stores.

Both are async context managers, and langgraph's SQLite checkpointer in particular must be
entered and exited within one task. Keeping that in one helper means callers never hand-roll it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .config import AgentSettings, load_agent_settings
from .memory import MemoryStore

#: Our pydantic state types, declared to the checkpointer's serializer.
#:
#: Without this, langgraph logs "Deserializing unregistered type ... This will be blocked in a
#: future version" on every thread resume. Registering them now means a langgraph upgrade cannot
#: quietly turn short-term memory into a hard failure. `from_conn_string()` accepts no serde
#: argument, which is why the connection is opened here instead.
STATE_TYPES: tuple[tuple[str, str], ...] = (
    ("agent.state", "AgentState"),
    ("agent.state", "PlanStep"),
    ("agent.state", "Observation"),
    ("agent.state", "Citation"),
    ("agent.state", "GuardrailEvent"),
    ("agent.state", "Fact"),
    ("agent.state", "MemoryEvent"),
    ("agent.state", "ConversationTurn"),
    ("agent.state", "Budget"),
)


@asynccontextmanager
async def open_memory(
    settings: AgentSettings | None = None,
    *,
    short_term: bool = True,
    memory_db: str | None = None,
    checkpoint_db: str | None = None,
) -> AsyncIterator[tuple[MemoryStore, Any | None]]:
    """Yield (long_term_store, checkpointer).

    Short-term memory is the LangGraph checkpointer, keyed by `thread_id`: the current
    conversation, and disposable. Long-term memory is our own `facts` table, keyed by
    `(key, scope)`: durable, and gated by the five-gate write rule. They are separate mechanisms
    because the decision about what survives a conversation is the whole point -- one store with
    a retention flag would blur exactly the distinction worth being able to explain.
    """
    settings = settings or load_agent_settings()

    async with MemoryStore(memory_db or settings.memory_db) as store:
        if not short_term:
            yield store, None
            return

        import aiosqlite
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with aiosqlite.connect(checkpoint_db or settings.checkpoint_db) as conn:
            yield store, AsyncSqliteSaver(
                conn, serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)
            )

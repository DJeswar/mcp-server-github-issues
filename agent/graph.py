"""Graph assembly. Wiring only -- every decision lives in a node or in `route_after_plan`.

    START -> load_memory -> plan -> (call_tool) -> execute -> plan -> ...
                                 \\-> (finish)  -> synthesize -> guard_outbound -> persist -> END

The inbound guard is not a node: it must annotate a tool result before that result becomes an
Observation consumed by planning and synthesis. It runs inside `execute`; see
`guardrails/inbound.py`.

`build_graph` returns an **uncompiled** StateGraph on purpose. In langgraph 1.x the SQLite
checkpointer (`AsyncSqliteSaver.from_conn_string`) is an async context manager, so compilation has
to happen inside that context. Separating build from compile lets `run_agent` own the saver's
lifetime without this module knowing anything about persistence.
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from .config import AgentSettings
from .mcp_client import Toolset
from .memory import MemoryStore
from .models.base import ChatModel, ToolSpec
from .nodes import (
    complete_turn_node,
    execute_node,
    guard_outbound_node,
    load_memory_node,
    persist_node,
    plan_node,
    synthesize_node,
)
from .state import AgentState


def route_after_plan(state: AgentState) -> str:
    """Pure function of state -- it selects a node and mutates nothing.

    That is why budget enforcement is in `plan_node` instead of here: a conditional edge cannot
    record *why* it stopped, and an answer that cannot explain its own incompleteness is worse
    than no answer.
    """
    action = state.next_action
    if action is None or action.action == "finish":
        return "synthesize"
    return "execute"


def build_graph(
    *,
    model: ChatModel,
    toolset: Toolset,
    tools: list[ToolSpec],
    settings: AgentSettings,
    store: MemoryStore | None = None,
    session_id: str = "default",
    scope: str = "global",
) -> StateGraph:
    """`store=None` runs the loop with no long-term memory, which stays a supported mode."""
    graph = StateGraph(AgentState)

    graph.add_node(
        "load_memory",
        partial(
            load_memory_node, store=store, scope=scope, limit=settings.recall_limit
        ),
    )
    graph.add_node("plan", partial(plan_node, model=model, tools=tools, settings=settings))
    graph.add_node(
        "execute", partial(execute_node, toolset=toolset, mode=settings.guardrail_mode)
    )
    graph.add_node("synthesize", partial(synthesize_node, model=model))
    graph.add_node(
        "guard_outbound", partial(guard_outbound_node, mode=settings.guardrail_mode)
    )
    graph.add_node(
        "persist",
        partial(
            persist_node, model=model, store=store, session_id=session_id, scope=scope
        ),
    )
    graph.add_node("complete_turn", complete_turn_node)

    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"execute": "execute", "synthesize": "synthesize"},
    )
    graph.add_edge("execute", "plan")
    # persist runs AFTER synthesis, not before: what is worth remembering can depend on what the
    # answer turned out to be, and a failed run should not leave facts behind. The outbound guard
    # sits between them so a blocked answer is still recorded in the event log.
    graph.add_edge("synthesize", "guard_outbound")
    graph.add_edge("guard_outbound", "persist")
    graph.add_edge("persist", "complete_turn")
    graph.add_edge("complete_turn", END)

    return graph

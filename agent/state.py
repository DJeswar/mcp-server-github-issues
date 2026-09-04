"""Graph state.

Deviation from the Phase 3 sketch, stated deliberately: the sketch had a single static `Plan`
with a `step_index`. This uses **iterative planning** instead -- `plan` is re-invoked before each
action and appends to `plan_history`.

Why: the runbook's worked example needs step 2's arguments to depend on step 1's result ("find
the next release, THEN find what blocks it"). A static plan cannot express that without inventing
a placeholder/template language, and a template language is machinery we would then have to
defend. Re-planning with the observations in view handles dependency naturally, and
`plan_history` is a *better* trace than a static plan because it records the reasoning at each
step rather than only up front.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Action = Literal["call_tool", "finish"]


class PlanStep(BaseModel):
    """One planner decision. The sequence of these is the trace."""

    index: int
    action: Action
    why: str = ""
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    """The result of one tool call.

    Keeps the *whole* envelope, not just `items`, so `backend`, `fetched_at`, `has_more` and
    `notes` survive into synthesis. That is what lets the answer say "3 of 12, more pages
    available" instead of quietly implying completeness.
    """

    step: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    envelope: dict[str, Any] | None = None
    error: str | None = None

    @property
    def items(self) -> list[dict[str, Any]]:
        return list((self.envelope or {}).get("items") or [])

    @property
    def issue_numbers(self) -> list[int]:
        return [int(i["number"]) for i in self.items if isinstance(i.get("number"), int)]


class Citation(BaseModel):
    issue: int
    claim: str


class GuardrailEvent(BaseModel):
    """A policy decision worth counting.

    `direction` is about the agent's boundary, not the user's: **inbound** is data entering the
    agent (tool results), **outbound** is anything leaving it — a response to the user, or a tool
    call the agent tried to make. Phase 4c fills in the injection detectors; Phase 4a already
    emits `tool_allowlist` refusals, because Phase 5 needs "a tool call that should be refused"
    to be a countable event rather than a log line someone has to grep for.
    """

    detector: str
    direction: Literal["inbound", "outbound"]
    source: str
    action: str
    span: tuple[int, int] | None = None
    detail: str = ""


class Fact(BaseModel):
    """A long-term fact recalled for this question."""

    key: str
    value: str
    source_quote: str = ""
    created_at: str = ""
    session_id: str = ""


class MemoryEvent(BaseModel):
    """One write decision, kept whether or not it was accepted.

    Rejections are recorded on purpose: "we considered storing this and here is which gate said
    no" is the evidence that the write rule is a rule and not a slogan.
    """

    action: Literal["written", "superseded", "rejected"]
    key: str
    value: str
    reason: str = ""
    failed_gates: list[str] = Field(default_factory=list)


class ConversationTurn(BaseModel):
    """One completed turn retained by the short-term checkpointer."""

    question: str
    answer: str


def _append_recent_turns(
    left: list[ConversationTurn], right: list[ConversationTurn]
) -> list[ConversationTurn]:
    """Append completed turns while bounding checkpoint growth."""
    return (left + right)[-8:]


class Budget(BaseModel):
    """Counters. The limits live in AgentSettings; these are the running totals."""

    steps: int = 0
    tool_calls: int = 0
    no_progress: int = 0
    #: monotonic clock at the first planning turn; 0.0 until then
    started_at: float = 0.0
    elapsed: float = 0.0


class AgentState(BaseModel):
    question: str
    thread_id: str = "default"

    #: The only cross-turn state. Per-turn plans, observations and counters are replaced when a
    #: new AgentState is submitted to an existing checkpoint thread.
    conversation: Annotated[list[ConversationTurn], _append_recent_turns] = Field(
        default_factory=list
    )

    #: long-term facts recalled for this question, from `load_memory`
    recalled_facts: list[Fact] = Field(default_factory=list)
    memory_events: list[MemoryEvent] = Field(default_factory=list)

    # Per-turn collections deliberately have no reducer. A new question on the same checkpoint
    # replaces them instead of accidentally reasoning over an earlier question's tool results.
    # Nodes therefore return the complete collection built so far in this turn.
    plan_history: list[PlanStep] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    guardrail_events: list[GuardrailEvent] = Field(default_factory=list)

    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    terminated_because: str | None = None

    # set by `plan`, consumed by the conditional edge and by `execute`
    next_action: PlanStep | None = None

    @property
    def last_observation(self) -> Observation | None:
        return self.observations[-1] if self.observations else None

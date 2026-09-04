"""Agent settings. Same shape as server/config.py: resolved once, fails loudly at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from server.errors import ConfigError

Backend = Literal["stub", "replay", "groq", "gemini", "auto"]
GuardrailMode = Literal["enforce", "report"]
SslTrust = Literal["certifi", "system"]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASSETTE_DIR = REPO_ROOT / "evals" / "cassettes"

#: The only tools the agent may call. The server is read-only, but an explicit allowlist means a
#: model inventing a tool name is refused and logged rather than producing a confusing error.
ALLOWED_TOOLS = (
    "list_issues",
    "get_issue",
    "search_issues",
    "list_labels",
    "list_milestones",
)


def _int(env: dict[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float(env: dict[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be > 0, got {value}")
    return value


@dataclass(frozen=True)
class AgentSettings:
    llm_backend: Backend
    max_steps: int
    max_tool_calls: int
    max_wall_clock: float
    no_progress_limit: int
    cassette_dir: Path
    record_cassettes: bool
    #: long-term memory (our tables). ':memory:' keeps a run entirely ephemeral.
    memory_db: str
    #: short-term conversation state (the LangGraph checkpointer)
    checkpoint_db: str
    recall_limit: int
    #: 'enforce' acts on detections; 'report' logs what WOULD have fired and changes nothing.
    #: Phase 5 needs report mode to tell "the guardrail worked" from "the model was not tempted".
    guardrail_mode: GuardrailMode
    #: Live-model credentials are deliberately excluded from the dataclass repr.
    groq_api_key: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.5-flash"
    model_timeout: float = 30.0
    model_max_output_tokens: int = 4096
    ssl_trust: SslTrust = "certifi"

    @property
    def recursion_limit(self) -> int:
        """LangGraph's own limit, deliberately set ABOVE our budgets.

        `recursion_limit` is an invoke-time config key in langgraph 1.x, not a compile()
        argument. It must never be the limit that fires first: if it does, the framework aborts
        the run and the 'answer with what you have' path never executes. Each iteration costs
        two supersteps (plan + execute), so this leaves generous headroom.
        """
        return 2 * self.max_steps + 10


def load_agent_settings(env: dict[str, str] | None = None) -> AgentSettings:
    if env is None:
        load_dotenv()
        env = dict(os.environ)

    backend = (env.get("LLM_BACKEND") or "stub").strip().lower()
    if backend not in ("stub", "replay", "groq", "gemini", "auto"):
        raise ConfigError(
            "LLM_BACKEND must be 'stub', 'replay', 'groq', 'gemini' or 'auto', "
            f"got {backend!r}"
        )
    groq_key = (env.get("GROQ_API_KEY") or "").strip() or None
    gemini_key = (env.get("GEMINI_API_KEY") or "").strip() or None
    if backend == "groq" and not groq_key:
        raise ConfigError("LLM_BACKEND=groq requires GROQ_API_KEY")
    if backend == "gemini" and not gemini_key:
        raise ConfigError("LLM_BACKEND=gemini requires GEMINI_API_KEY")
    if backend == "auto" and not (groq_key or gemini_key):
        raise ConfigError(
            "LLM_BACKEND=auto requires GROQ_API_KEY, GEMINI_API_KEY, or both"
        )

    wall_raw = (env.get("AGENT_MAX_WALL_CLOCK") or "60").strip()
    try:
        wall = float(wall_raw)
    except ValueError as exc:
        raise ConfigError(f"AGENT_MAX_WALL_CLOCK must be a number, got {wall_raw!r}") from exc
    if wall <= 0:
        raise ConfigError("AGENT_MAX_WALL_CLOCK must be > 0")

    guardrail_mode = (env.get("GUARDRAIL_MODE") or "enforce").strip().lower()
    if guardrail_mode not in ("enforce", "report"):
        raise ConfigError(
            f"GUARDRAIL_MODE must be 'enforce' or 'report', got {guardrail_mode!r}"
        )

    ssl_trust = (env.get("SSL_TRUST_STORE") or "certifi").strip().lower()
    if ssl_trust not in ("certifi", "system"):
        raise ConfigError(
            f"SSL_TRUST_STORE must be 'certifi' or 'system', got {ssl_trust!r}"
        )

    cassette_dir = (env.get("CASSETTE_DIR") or "").strip()

    return AgentSettings(
        llm_backend=backend,  # type: ignore[arg-type]
        max_steps=_int(env, "AGENT_MAX_STEPS", 8),
        max_tool_calls=_int(env, "AGENT_MAX_TOOL_CALLS", 12),
        max_wall_clock=wall,
        no_progress_limit=_int(env, "AGENT_NO_PROGRESS_LIMIT", 2),
        cassette_dir=Path(cassette_dir) if cassette_dir else DEFAULT_CASSETTE_DIR,
        record_cassettes=(env.get("RECORD_CASSETTES") or "0").strip() not in ("", "0", "false"),
        memory_db=(env.get("MEMORY_DB") or "agent_memory.sqlite3").strip(),
        checkpoint_db=(env.get("CHECKPOINT_DB") or "agent_checkpoints.sqlite3").strip(),
        recall_limit=_int(env, "AGENT_RECALL_LIMIT", 5),
        guardrail_mode=guardrail_mode,  # type: ignore[arg-type]
        groq_api_key=groq_key,
        gemini_api_key=gemini_key,
        groq_model=(env.get("GROQ_MODEL") or "").strip() or "llama-3.3-70b-versatile",
        gemini_model=(env.get("GEMINI_MODEL") or "").strip() or "gemini-2.5-flash",
        model_timeout=_float(env, "MODEL_TIMEOUT_SECONDS", 30.0),
        model_max_output_tokens=_int(env, "MODEL_MAX_OUTPUT_TOKENS", 4096, minimum=64),
        ssl_trust=ssl_trust,  # type: ignore[arg-type]
    )

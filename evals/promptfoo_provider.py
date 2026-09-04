"""promptfoo custom provider: lets promptfoo drive this agent.

promptfoo calls `call_api(prompt, options, context)` and expects
`{"output": ..., "error": ...}`. We return the answer as `output` and attach the interesting
parts of the run (tools, guardrail events, citations, memory decisions) as `metadata`, so
promptfoo assertions can inspect behaviour rather than only text.

CREDENTIALS: none. Runs the same offline path as evals/runner.py.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.config import load_agent_settings  # noqa: E402
from agent.mcp_client import InProcessToolset  # noqa: E402
from agent.memory import MemoryStore  # noqa: E402
from agent.run import run_agent  # noqa: E402
from evals.runner import build_model  # noqa: E402


async def _run(question: str, config: dict[str, Any]) -> dict[str, Any]:
    env: dict[str, str] = {}
    if config.get("max_steps"):
        env["AGENT_MAX_STEPS"] = str(config["max_steps"])
    if config.get("guardrail_mode"):
        env["GUARDRAIL_MODE"] = str(config["guardrail_mode"])

    server_env: dict[str, str] = {}
    if fixture_dir := config.get("fixture_dir"):
        server_env["FIXTURE_DIR"] = str(REPO_ROOT / fixture_dir)

    async with MemoryStore(":memory:", clock=lambda: "2026-08-01T00:00:00+00:00") as store:
        state = await run_agent(
            question,
            settings=load_agent_settings(env),
            toolset=InProcessToolset(env=server_env),
            model=build_model(config.get("model")),
            thread_id="promptfoo",
            session_id="promptfoo",
            store=store,
        )

    return {
        "output": state.answer or "",
        "metadata": {
            "tools": [obs.tool for obs in state.observations],
            "tool_errors": [obs.error for obs in state.observations if obs.error],
            "citations": sorted(c.issue for c in state.citations),
            "guardrail_detectors": sorted({e.detector for e in state.guardrail_events}),
            "guardrail_directions": sorted({e.direction for e in state.guardrail_events}),
            "guardrail_count": len(state.guardrail_events),
            "memory_written": [
                e.key for e in state.memory_events if e.action in ("written", "superseded")
            ],
            "memory_rejected": [e.key for e in state.memory_events if e.action == "rejected"],
            "terminated_because": state.terminated_because,
            "tool_calls": state.budget.tool_calls,
        },
    }


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = (options or {}).get("config") or {}
    # promptfoo may pass per-test vars; they take precedence over provider-level config
    config = {**config, **((context or {}).get("vars") or {})}
    try:
        return asyncio.run(_run(prompt, config))
    except Exception as exc:  # promptfoo shows `error` as a failed assertion
        return {"output": "", "error": f"{type(exc).__name__}: {exc}"}

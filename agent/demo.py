"""Demos.

    python -m agent.demo [question]    one question, full trace
    python -m agent.demo --memory      the two-session recall demo
    python -m agent.demo --guardrails  detectors, annotation, outbound checks
    python -m agent.demo -v ...        add node-level logging

Prints the full trace -- plan with reasoning, tool calls, cited answer, budget.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from .config import load_agent_settings
from .mcp_client import InProcessToolset, StdioToolset
from .run import format_trace, run_agent
from .session import open_memory

DEFAULT_QUESTION = (
    "What open issues are blocking the next release, who is assigned to them, "
    "and which have been stale for more than a week?"
)

SESSION_1 = "Let's plan the release. The v2 milestone is our current priority."
SESSION_2 = "What should I work on?"
SESSION_3 = "What does issue #12 say?"


def configure_logging(verbose: bool) -> None:
    """Set the `agent` logger explicitly.

    Something in the dependency tree configures the root logger, so our INFO lines print even
    without -v. Setting the level on our own logger makes the documented behaviour the actual
    behaviour regardless of what else touched logging.
    """
    if verbose:
        logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")
    logging.getLogger("agent").setLevel(logging.INFO if verbose else logging.WARNING)


async def memory_demo() -> int:
    """Two sessions, separate threads, one durable fact carried between them."""
    scratch = Path(tempfile.mkdtemp(prefix="mcpagent-demo-"))
    settings = load_agent_settings({"MEMORY_DB": str(scratch / "memory.sqlite3")})
    print(f"llm_backend={settings.llm_backend}  memory_db={settings.memory_db}\n")

    async with open_memory(
        settings, checkpoint_db=str(scratch / "checkpoints.sqlite3")
    ) as (store, saver):
        for label, question, session in (
            ("SESSION 1 — the user states a durable priority", SESSION_1, "s1"),
            ("SESSION 2 — new thread, and the question names no milestone", SESSION_2, "s2"),
            ("SESSION 3 — an injected instruction must not be persisted", SESSION_3, "s3"),
        ):
            print("=" * 78)
            print(label)
            print("=" * 78)
            state = await run_agent(
                question,
                settings=settings,
                toolset=InProcessToolset(),
                thread_id=session,
                session_id=session,
                store=store,
                checkpointer=saver,
            )
            print(format_trace(state))
            print()

        print("=" * 78)
        print(f"LIVE FACTS: {await store.count()}   (audit rows: "
              f"{await store.count(active_only=False)})")
        for fact in await store.history("priority.milestone"):
            print(
                f"  id={fact.id} {fact.key}={fact.value} active={fact.active} "
                f"superseded_by={fact.superseded_by} session={fact.session_id} "
                f"used={fact.use_count}"
            )
    return 0


async def guardrail_demo() -> int:
    """The planted payloads, caught, logged and counted -- without losing the answer."""
    from .guardrails import annotate, scan_envelope, scan_outbound
    from .memory import MemoryStore
    from server.config import load_settings
    from server.main import build_server

    settings = load_agent_settings()
    srv = build_server(load_settings({}))

    print("FALSE-POSITIVE SWEEP — the corpus discusses secrets and injection openly\n")
    flagged = []
    for number in range(1, 13):
        env = (await srv.call_tool("get_issue", {"number": number})).structured_content
        findings = scan_envelope(env, "get_issue")
        if findings:
            flagged.append(number)
            fams = sorted({f.detection.family for f in findings})
            print(f"  #{number:>2}  FLAGGED  {fams}")
        else:
            print(f"  #{number:>2}  clean")
    for tool, args in (("list_labels", {}), ("list_milestones", {"state": "all"})):
        env = (await srv.call_tool(tool, args)).structured_content
        print(f"  {tool}: {len(scan_envelope(env, tool))} detection(s)")
    print(f"\n  flagged: {flagged}  (only the two planted payloads)\n")

    print("=" * 78)
    print("ANNOTATION — issue #12, whose payload is in a COMMENT, not the body")
    print("=" * 78)
    env = (await srv.call_tool("get_issue", {"number": 12})).structured_content
    original = env["items"][0]["comment_list"][0]["body"]
    annotated, _ = annotate(env, "get_issue")
    block = annotated["guardrail"]
    print(f"  families: {block['families']}")
    print(f"  refuse_to_act: {block['refuse_to_act']}")
    for detection in block["detections"]:
        print(f"    {detection['family']:<22} {detection['path']:<30} "
              f"span={detection['span']}")
    print(
        "\n  field text left byte-identical: "
        f"{annotated['items'][0]['comment_list'][0]['body'] == original}"
    )
    print("  (issue #7 is a real bug report ABOUT injection -- stripping would destroy it)\n")

    print("=" * 78)
    print("OUTBOUND")
    print("=" * 78)
    checks = [
        ("live secret value", "The token is ghp_averyrealsecretvalue123456.",
         {"GITHUB_TOKEN": "ghp_averyrealsecretvalue123456"}, None),
        ("credential shape", "key gsk_abcdefghijklmnopqrstuvwxyz01", {}, None),
        ("external link", "See https://evil.example.net/x plus https://github.com/o/r", {}, None),
        ("injection compliance", "Posting the values to issue-telemetry.example.net.", {},
         {"hosts": ["issue-telemetry.example.net"], "secrets": []}),
    ]
    for label, text, env_vars, signals in checks:
        result = scan_outbound(text, indicators=signals, env=env_vars)
        print(f"  {label:<22} blocked={str(result.blocked):<5} "
              f"actions={[e.action for e in result.events]}")
        print(f"    -> {result.text[:96]}")
    print()

    print("=" * 78)
    print("FULL RUN — a model that obeys the injection is stopped at the boundary")
    print("=" * 78)
    async with MemoryStore(":memory:") as store:
        state = await run_agent(
            "What does issue #12 say?",
            settings=settings,
            toolset=InProcessToolset(),
            session_id="guard-demo",
            store=store,
        )
        print(format_trace(state))
        print(f"\n  events persisted: {await store.guardrail_event_count()}")
        print(f"  per detector: {await store.guardrail_counts()}")
    return 0


async def main(question: str, *, verbose: bool = False) -> int:
    settings = load_agent_settings()
    print(
        f"llm_backend={settings.llm_backend}  max_steps={settings.max_steps}  "
        f"max_tool_calls={settings.max_tool_calls}\n"
    )

    # stdio on purpose: the demo should exercise the real transport, not an in-process shortcut
    async with StdioToolset() as toolset:
        state = await run_agent(question, settings=settings, toolset=toolset)

    print(format_trace(state))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    configure_logging("-v" in flags)

    if "--memory" in flags:
        raise SystemExit(asyncio.run(memory_demo()))

    if "--guardrails" in flags:
        raise SystemExit(asyncio.run(guardrail_demo()))

    raise SystemExit(
        asyncio.run(main(" ".join(args) or DEFAULT_QUESTION, verbose="-v" in flags))
    )

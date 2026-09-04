"""Web UI for the demo. `python -m app.main`, or the container entrypoint.

Starlette rather than FastAPI or Streamlit on purpose: Starlette already ships as a dependency of
`mcp`, so the web layer adds **no new runtime dependency** and the free-tier container stays small
and cold-starts fast.

CREDENTIALS: none needed. Defaults to the fixture backend and the scripted model, so a deployed
Space works immediately with nothing configured. See the env table in docs/deploy.md to point it
at a live repository.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from langgraph.checkpoint.memory import InMemorySaver

from agent import __version__
from agent.config import load_agent_settings
from agent.mcp_client import InProcessToolset
from agent.memory import MemoryStore
from agent.run import run_agent
from agent.models.live import ModelProviderError

log = logging.getLogger("app")

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"

MAX_QUESTION_CHARS = 500
SESSION_COOKIE = "mcp_agent_session"
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
SESSION_MAX_AGE = 7 * 24 * 60 * 60

#: A public demo without a limiter is an invitation. In-memory and per-process, which is fine for
#: a single free-tier container; put a real limiter in front if this ever gets traffic.
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

EXAMPLES = [
    "What open issues are blocking the next release, who is assigned to them, "
    "and which have been stale for more than a week?",
    "What does issue #12 say?",
    "Which labels exist in this repo?",
    "What does issue #9999 say?",
]

_state: dict[str, object] = {}
_hits: dict[str, list[float]] = {}
_lock = asyncio.Lock()


def _session_id(request: Request) -> tuple[str, bool]:
    existing = request.cookies.get(SESSION_COOKIE, "")
    if SESSION_RE.fullmatch(existing):
        return existing, False
    return secrets.token_urlsafe(32), True


def _with_session(
    response: HTMLResponse | JSONResponse,
    request: Request,
    session_id: str,
    created: bool,
) -> HTMLResponse | JSONResponse:
    if created:
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=(
                request.url.scheme == "https"
                or os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true")
            ),
        )
    return response


def _rate_limited(client: str) -> bool:
    now = time.monotonic()
    window = _hits.setdefault(client, [])
    window[:] = [t for t in window if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(window) >= RATE_LIMIT_REQUESTS:
        return True
    window.append(now)
    return False


def _toolset_from_environment() -> InProcessToolset:
    """Opt into ambient data-backend settings at the application boundary.

    InProcessToolset deliberately defaults to an empty environment so tests cannot accidentally
    hit GitHub. The deployed app is the place where the operator's ISSUES_BACKEND/GITHUB_REPO
    choices must be honored, so it passes them explicitly.
    """
    return InProcessToolset(env=dict(os.environ))


@asynccontextmanager
async def lifespan(app: Starlette):
    settings = load_agent_settings()
    # ':memory:' by default so a public demo keeps nothing between restarts. Point MEMORY_DB at a
    # file to make recall survive; on Hugging Face's free tier storage is ephemeral anyway.
    store = MemoryStore(os.environ.get("MEMORY_DB", ":memory:"))
    await store.open()
    _state["settings"] = settings
    _state["store"] = store
    # Checkpoints are intentionally process-local in the public demo: they make a browser
    # conversation coherent without writing visitor transcripts to disk.
    _state["checkpointer"] = InMemorySaver()
    _hits.clear()
    log.info(
        "app %s ready: llm=%s guardrails=%s",
        __version__,
        settings.llm_backend,
        settings.guardrail_mode,
    )
    try:
        yield
    finally:
        await store.close()
        _state.clear()


async def homepage(request: Request) -> HTMLResponse:
    session_id, created = _session_id(request)
    return _with_session(
        HTMLResponse(INDEX.read_text(encoding="utf-8")),
        request,
        session_id,
        created,
    )


async def health(request: Request) -> JSONResponse:
    settings = _state.get("settings")
    live_backend_selected = getattr(settings, "llm_backend", None) in {
        "groq",
        "gemini",
        "auto",
    }
    live_credentials_present = bool(
        getattr(settings, "groq_api_key", None)
        or getattr(settings, "gemini_api_key", None)
    )
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "llm_backend": getattr(settings, "llm_backend", None),
            "guardrail_mode": getattr(settings, "guardrail_mode", None),
            "issues_backend": os.environ.get("ISSUES_BACKEND", "fixture"),
            "live_model_configured": live_backend_selected and live_credentials_present,
            "groq_model": getattr(settings, "groq_model", None),
            "gemini_model": getattr(settings, "gemini_model", None),
        }
    )


async def examples(request: Request) -> JSONResponse:
    return JSONResponse({"examples": EXAMPLES})


async def ask(request: Request) -> JSONResponse:
    client = request.client.host if request.client else "unknown"
    if _rate_limited(client):
        return JSONResponse(
            {"error": f"Rate limit: {RATE_LIMIT_REQUESTS} questions per "
                      f"{RATE_LIMIT_WINDOW_SECONDS}s. Try again shortly."},
            status_code=429,
        )

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)

    question = str(payload.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "Ask a question."}, status_code=400)
    if len(question) > MAX_QUESTION_CHARS:
        return JSONResponse(
            {"error": f"Questions are capped at {MAX_QUESTION_CHARS} characters."},
            status_code=400,
        )

    settings = _state["settings"]
    store = _state["store"]
    checkpointer = _state["checkpointer"]
    session_id, session_created = _session_id(request)

    # One question at a time: the free CPU tier has a single worker, and serialising here gives a
    # clear queue instead of thrashing.
    async with _lock:
        try:
            state = await run_agent(
                question,
                settings=settings,  # type: ignore[arg-type]
                toolset=_toolset_from_environment(),
                thread_id=f"web:{session_id}",
                session_id=f"web:{session_id}",
                scope=f"web:{session_id}",
                checkpointer=checkpointer,
                store=store,  # type: ignore[arg-type]
            )
        except ModelProviderError as exc:
            log.warning("live model unavailable: %s", exc)
            return _with_session(
                JSONResponse(
                    {"error": f"Live model unavailable: {exc}"}, status_code=502
                ),
                request,
                session_id,
                session_created,
            )
        except Exception as exc:  # never leak a traceback to a public endpoint
            log.exception("run failed")
            return JSONResponse(
                {"error": f"The agent failed: {type(exc).__name__}."}, status_code=500
            )

    response = JSONResponse(
        {
            "answer": state.answer or "",
            "plan": [
                {
                    "index": step.index,
                    "action": step.action,
                    "tool": step.tool,
                    "args": step.args,
                    "why": step.why,
                }
                for step in state.plan_history
            ],
            "tool_calls": [
                {
                    "step": obs.step,
                    "tool": obs.tool,
                    "args": obs.args,
                    "ok": obs.ok,
                    "items": len(obs.items),
                    "error": obs.error,
                    "notes": (obs.envelope or {}).get("notes", []),
                    "has_more": (obs.envelope or {}).get("has_more"),
                }
                for obs in state.observations
            ],
            "citations": [{"issue": c.issue, "claim": c.claim} for c in state.citations],
            "guardrail_events": [
                {
                    "detector": e.detector,
                    "direction": e.direction,
                    "source": e.source,
                    "action": e.action,
                    "detail": e.detail,
                }
                for e in state.guardrail_events
            ],
            "recalled_facts": [
                {"key": f.key, "value": f.value, "source_quote": f.source_quote}
                for f in state.recalled_facts
            ],
            "memory_events": [
                {
                    "action": e.action,
                    "key": e.key,
                    "value": e.value,
                    "reason": e.reason,
                }
                for e in state.memory_events
            ],
            "budget": {
                "planning_turns": state.budget.steps,
                "tool_calls": state.budget.tool_calls,
            },
            "terminated_because": state.terminated_because,
            "backend": {
                "llm": getattr(settings, "llm_backend", None),
                "issues": (state.observations[0].envelope or {}).get("backend")
                if state.observations
                else None,
                "repo": (state.observations[0].envelope or {}).get("repo")
                if state.observations
                else None,
            },
        }
    )
    return _with_session(response, request, session_id, session_created)


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/api/health", health),
        Route("/api/examples", examples),
        Route("/api/ask", ask, methods=["POST"]),
    ],
    lifespan=lifespan,
)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    # 7860 is the portable local default; Render injects its own PORT automatically.
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "7860")),
        log_level="info",
    )


if __name__ == "__main__":
    main()

# Project Context

An agentic assistant over live data, built on a custom MCP server that exposes a GitHub repository's Issues as agent tools. The agent plans multi-step questions, calls those tools, keeps short- and long-term memory, and defends against prompt injection. Built as a portfolio project targeting AI Engineer roles in India, with a published MCP-registry listing, an adversarial eval suite gated in CI, and a deployed demo.

**Build strategy:** code first, integrations last. The server reads data through a swappable provider interface. A local JSON fixture backend is the default and needs no credentials; the live GitHub REST backend is opt-in via one environment variable. The whole stack — server, agent, memory, guardrails, evals — is built and tested with zero accounts on this machine, then flipped to live data on a second machine where the real repo and API keys live.

# About Me

I'm a GenAI/AI engineer with a background in LangChain, LangGraph, RAG, and multi-agent orchestration. I prefer concise, direct explanations. Treat me as someone who understands the concepts — don't over-explain basics, do explain trade-offs.

# Constraints

- Free-tier tools and APIs ONLY. Never suggest a paid service or paid tier without explicitly flagging it as paid and giving a free alternative.
- Primary LLM: Groq (fast, low daily quota). Fallback: Gemini Flash. Dev/offline: local Ollama.
- Always show your plan and wait for my approval before writing code on any multi-step task.
- Always ask clarifying questions before starting an ambiguous task.
- Keep commits small and working — I want a demoable checkpoint at the end of every session, not one giant commit at the end.
- This project will be published publicly. Never hardcode secrets — always read them from environment variables. Flag anything that could leak PII or credentials before it ships.

# Environment

This machine is a build-only environment. Do not assume anything below is present without checking.

- **OS/shell:** Windows 11, PowerShell 5.1. No `&&` or `||` chaining, no ternary `?:`, no `??`. Use `;` and `if ($?) { }`. Unix commands (`head`, `tail`, `which`, `touch`) do not exist.
- **Python:** 3.14.0 at `C:\Program Files\Python314` — the only interpreter installed. Project venv at `.venv`.
- **Node:** 25.9.0 with npx — used for the MCP Inspector and (later) promptfoo.
- **`git`: installed** (`git 2.53.0.windows.3`). The folder is not initialized as a repository
  because the destination account/repository belongs to the handoff PC.
- **`docker`: NOT INSTALLED.** Only needed at Phase 7.
- **Credentials: NONE set.** `GITHUB_TOKEN`, `GROQ_API_KEY`, `GEMINI_API_KEY` are all unset, by intent. Do not write code that fails at import time when a key is missing — degrade to the offline path instead.
- **The network does TLS inspection.** Outbound HTTPS is re-signed by a corporate CA that `certifi` does not carry, so any library using certifi's bundle fails with `CERTIFICATE_VERIFY_FAILED`. Set `SSL_TRUST_STORE=system` to use the OS certificate store (via `truststore`). Expect this for every new HTTP client added to the project, not just the GitHub one.

Because Python 3.14 is bleeding edge, treat any dependency install as something to verify rather than assume. If a compiled wheel (e.g. `pydantic-core`) has no `cp314` build, report it and propose installing Python 3.12/3.13 alongside — do not silently pin to old versions to make it resolve.

# Data Backend Rule

- `ISSUES_BACKEND=fixture` (default) reads `server/fixtures/*.json`. No network, no credentials.
- `ISSUES_BACKEND=github` reads the live GitHub REST API. `GITHUB_TOKEN` is optional — unauthenticated public-repo reads work at 60 req/hr.
- **Both providers must return identical model types and identical output shapes for the same logical query.** This invariant is what lets fixture-built agent code work unchanged against live data. It has a dedicated test; do not break it.
- Fixture timestamps are fixed, and anything time-relative (e.g. "stale for more than a week") is computed against `FIXTURE_NOW`, not the wall clock. Determinism here is what keeps the Phase 5 eval pass rate stable instead of drifting daily.

# Portability

This project gets zipped and moved to another laptop for account wiring. Therefore:

- No absolute paths in code or config.
- No machine-specific settings outside `.env`.
- `.env` is git-ignored; `.env.example` documents every variable and is committed.

# Checkpoint Rule (amended)

The runbook asks for a working commit per session. `git` is not installed, so until it is, each checkpoint is a dated entry in `docs/CHANGELOG.md` recording what works and how it was verified. Same discipline, no blocking install.

# Folder Structure

- `/server` — the MCP server: tool definitions, input schemas, provider layer
  - `/server/providers` — `base.py` (the interface), `fixture.py`, `github.py`
  - `/server/fixtures` — the seeded issue corpus as JSON, including planted injection payloads
- `/agent` — planner/executor loop, memory, guardrails
- `/evals` — normal + adversarial test cases, promptfoo config, results
- `/docs` — `runbook.md` (the original build guide), `spec.md`, `architecture.md`, `CHANGELOG.md`
- `/tests` — pytest suite
- `/.github/workflows` — CI eval-gating pipeline

# Current Status

All **10 implementation checkpoints** are built (0, 1, 2, 3, 4a, 4b, 4c, 5, 6, 7). Strict
runbook completion is **7/10** because the last three require account-bound public proof:

- Phase 5: 25/25 evals locally and workflow written; push to GitHub for a green Actions run.
- Phase 6: package, `server.json`, metadata and runbook ready; publish to PyPI/MCP Registry.
- Phase 7: web app, live-model integrations, Dockerfile and Render Free Blueprint ready; deploy.

There are **435 tests**. All non-stdio tests pass; all 10 real-stdio transport tests pass. The eval
suite remains normal 8/8, injection 8/8 and edge 9/9. See `docs/status.md` for the exact count and
`docs/handoff.md` for the other-PC account/key steps.

The live Groq (`openai/gpt-oss-20b`) and Gemini (`gemini-2.5-flash`) backends use documented HTTPS
APIs through `httpx`, validate JSON output, redact key values from provider errors, and support
transient Groq-to-Gemini fallback under `LLM_BACKEND=auto`. The web app honors live GitHub env
settings and isolates checkpoint/memory scope per browser.

# Library Gotchas — check, don't recall

Two major-version surprises have already cost time here. Introspect the installed package before
writing code against any of these.

- **`mcp` is 2.x.** `FastMCP` → `MCPServer` (`mcp.server.mcpserver`). Fields are snake_case
  (`input_schema`, `is_error`). A bare exception in a tool is **masked** to
  "Error executing tool <name>" — only `ToolError` delivers its message to the model. A pydantic
  return annotation is what produces `output_schema` and `structured_content`.
- **`langgraph` is 1.x.** `StateGraph` is unchanged, but `recursion_limit` is an **invoke-time
  config key**, not a `compile()` argument, and `AsyncSqliteSaver.from_conn_string` is an **async
  context manager**. Our own `max_steps` must fire before LangGraph's recursion limit, or the
  framework aborts and the "answer with what you have" path never runs.
- **`StdioToolset` is single-task.** The MCP stdio client uses anyio task groups; open and close
  must happen in the same asyncio task. Use `async with`, never a yielding pytest fixture.
- **Never use pytest's `tmp_path`/`tmp_path_factory`.** Use the `tmp_dir` fixture in
  `tests/conftest.py`. Both pytest temp configurations fail on this machine: the default keeps a
  `pytest-current` junction whose cleanup raises `PermissionError [WinError 5]` (every test passes,
  run exits 1), and a fixed `--basetemp` is wiped at session start while the IDE's file watcher
  holds the directory. Requesting the factory even once breaks the whole session's teardown.
- **langgraph checkpointer + our pydantic state:** register state types via
  `JsonPlusSerializer(allowed_msgpack_modules=…)` (see `agent/session.py`). Unregistered types
  only warn today but will be blocked in a future version. `from_conn_string()` takes no `serde`,
  so open the `aiosqlite` connection directly.
- **Groq/Gemini use HTTP, not SDKs.** Keep provider wire contracts in
  `tests/test_agent_live_models.py`; update model names through environment variables when a
  provider deprecates one.

# Phase status

The original runbook has **8 top-level phases (0 through 7)**. Phase 4 is split into 4a, 4b and
4c, so there are **10 implementation checkpoints** when those subphases are counted separately.

## Current count

- **Implementation:** 10/10 checkpoints built on this PC.
- **Strict runbook completion:** 7/10 checkpoints complete; Phases 5, 6 and 7 still require
  account-bound proof on the other PC.
- **Top-level view:** Phases 0–4 are complete; Phases 5–7 are implementation-complete but await
  CI, publication, and deployment respectively.

| Checkpoint | Built here | Verified here | External completion gate |
|---|---:|---:|---|
| 0 — scaffold | yes | yes | none |
| 1 — MCP server design | yes | yes | none |
| 2 — MCP server | yes | yes, including real stdio and a prior unauthenticated GitHub smoke | none |
| 3 — agent design | yes | yes | none |
| 4a — planner/executor | yes | yes | none |
| 4b — memory | yes | yes, including same-thread reset regression | none |
| 4c — guardrails | yes | yes | none |
| 5 — eval suite + CI | yes | 25/25 locally; workflow inspected | push to GitHub and obtain a green Actions run |
| 6 — publish MCP server | yes | sdist/wheel build locally | set identity, publish PyPI and Registry, paste listing URL |
| 7 — deploy + document | yes | web API/UI tests and Render Blueprint validation | connect GitHub to Render Free, deploy, paste demo URL |

## Current evidence

- **435 tests collected.** All non-stdio tests passed in one run; all 10 real-stdio transport
  tests passed in a separate run using a temporary interpreter bridge required only because the
  local `.venv` launcher was blocked by endpoint tooling.
- **25/25 evals:** normal 8/8, injection 8/8, edge 9/9.
- **Package builds:** `mcp_server_github_issues-0.1.0.tar.gz` and
  `mcp_server_github_issues-0.1.0-py3-none-any.whl`; both pass `twine check`.
- **Docker:** descriptor is complete, but Docker is not installed locally. Render can build it
  remotely from the connected GitHub repository.
- **Accounts/keys:** intentionally absent on this PC. No live Groq/Gemini request or deployment
  was claimed here; their HTTPS contracts are covered with offline mock transports.

The remaining work is enumerated in [handoff.md](handoff.md). It should not require application
code changes.

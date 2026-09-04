# Changelog

Session checkpoints. They originally stood in for git commits; git is now installed, but the
account-owned repository is intentionally created during handoff.

---

## 2026-09-02 — Session 8: Portfolio frontend redesign

**Changed — presentation layer only**

- Replaced the narrow, vertically stacked demo page with a responsive product dashboard:
  repository context and verified metrics, a chat-style agent workspace, and a tabbed execution
  inspector for plan, tools, safety, memory, and budget.
- Added visible health/backend status, example workflows, bounded-run progress, conversation
  turns, citation chips, accessible tabs, keyboard submission, character count, responsive
  breakpoints, and reduced-motion support.
- Kept the frontend fully self-contained: no framework, CDN, external font, analytics, new
  dependency, API change, agent change, or architecture change.

**Verified**

- Real browser run from question submission through `/api/ask` to rendered answer and trace.
- Desktop and 390px mobile layouts inspected; composer remains visible and the layout reflows.
- All inspector tabs work, the seeded injection appears in Safety as neutralized, and the browser
  reports no console warnings or errors.
- Web/release regression selection: 21/21 passed.

---

## 2026-09-01 — Session 7: Phases 5–7 implementation completed; account handoff prepared

**Built**

- Real Groq and Gemini HTTPS model backends, current overridable model defaults, sanitized
  provider errors, and transient `auto` fallback.
- Correct same-thread behavior: per-turn plan/observation/budget state resets, while a bounded
  eight-turn Q&A transcript remains in the LangGraph checkpoint.
- Public web isolation: random HTTP-only browser sessions, per-browser long-term-memory scopes,
  in-memory checkpoints, live GitHub env forwarding, and secret-safe health/error responses.
- MIT license, extended identity replacement, other-PC bootstrap/preflight scripts, definitive
  phase status, and full account/key handoff instructions.
- Render Free `render.yaml` Blueprint. The deployment recommendation moved away from Hugging Face
  because current HF docs require a paid plan to create new compute Spaces.

**Verified**

- 435 tests collected. All non-stdio tests passed together; all 10 stdio subprocess tests passed
  separately. The split was an environment workaround: this machine's `.venv` launcher was
  blocked, so a temporary base-interpreter bridge had to be forwarded to MCP child processes.
- Eval suite still 25/25: normal 8/8, injection 8/8, edge 9/9.
- Python compile pass, offline preflight pass, Render Blueprint/security tests pass.
- Package sdist and wheel rebuilt with SPDX license metadata and the fixture data package.

**Strict phase status:** implementation 10/10; runbook completion 7/10. Phase 5 needs a green
GitHub Actions run, Phase 6 needs public PyPI/Registry publication, and Phase 7 needs the Render
deployment URL. Those are intentionally deferred to the account-linked PC.

---

## 2026-08-31 — Session 1: Phase 0 (scaffold) + Phase 1 (server design)

**Phase 0 — scaffold**

- Relocated the project from `...\OneDrive - Cognizant\Desktop\project_resume` to
  `C:\dev\project_resume`. Reason: the project will hold a `.env` with API keys and a git repo
  destined to be public, and OneDrive sync contention corrupts `.git` internals and virtualenvs.
- Preserved the original build guide as `docs/runbook.md`, byte-identical (SHA-256 verified).
  It had to move before the project `CLAUDE.md` could be written — Windows is case-insensitive,
  so `CLAUDE.MD` and `CLAUDE.md` are the same path.
- Created the folder tree: `server/{providers,fixtures}`, `agent`, `evals`, `docs`, `tests`,
  `.github/workflows`.
- Wrote the project `CLAUDE.md`, amended against the runbook's assumptions to record what this
  machine actually has: no `git`, no `docker`, no credentials, Python 3.14 only, PowerShell 5.1.
- Added `requirements.txt` (MCP server deps only — LangGraph/Groq/Gemini deferred to Phase 3–4),
  `.gitignore`, `.env.example`, `pyproject.toml` (pytest config), `README.md` stub.
- Created `.venv` and installed the dependency set. **Verified:** Python 3.14.0, `import mcp,
  httpx, pydantic` succeeds, `pytest` → 3 passed. The Python 3.14 wheel risk did not
  materialize — `pydantic-core 2.46.5`, `rpds-py`, `cffi` and `pywin32` all resolved to native
  `cp314` wheels, so no source builds and no need for a second interpreter.
- Added `requirements.lock.txt` (full `pip freeze`) for the portability constraint — the second
  machine should reproduce this exact set rather than re-resolving.

**Correction made during Phase 0.** The `mcp>=1.2.0` floor resolved to **`mcp` 2.1.1**, a major
version ahead, shipping companion packages `mcp-types` and `httpx2`. The floor is now
`mcp>=2.1,<3`: left at `>=1.2`, the second machine could resolve to 1.x, whose server API
differs, and `server/main.py` would break there but not here. Phase 2 must confirm the 2.x
server/tool-registration API against the installed package rather than assume the 1.x shape.

**Phase 1 — server design**

- `docs/spec.md`: full server design — module layout, config, the `IssuesProvider` seam, all
  five tool descriptions and input schemas, the shared output envelope, GitHub client error and
  rate-limit handling, the `UNTRUSTED_FIELDS` contract, fixture corpus requirements.
- `docs/architecture.md`: system diagram, the rationale for the provider seam, the trust
  boundary, and the design decisions worth defending.

**Key decision.** The server reads through a swappable `IssuesProvider`. A committed JSON
fixture backend is the default and needs no credentials; the live GitHub REST backend is opt-in
via `ISSUES_BACKEND=github`. This is what makes a credential-free build possible, and it also
makes the Phase 5 eval pass rate deterministic and keeps the planted injection payloads in
version control.

**Deferred, deliberately:** `git` (not installed — needed before Phase 5 CI and Phase 6
publishing), `docker` (Phase 7), LLM keys (Phase 3–4), live repo + PAT / MCP Registry /
Hugging Face (second machine, Phases 6–7).

**Not yet done:** the OneDrive source folder still exists and must be deleted manually — it is
this session's working directory, and removing it mid-session breaks the shell.

**Next:** Phase 2 — implement the server from `docs/spec.md`, build the fixture corpus, write
the provider-parity test, and validate all five tools in the MCP Inspector.

---

## 2026-08-31 — Session 2: Phase 2 (MCP server implemented and verified)

**Verified**

- `pytest` → **138 passed** (config 18, normalize 16, fixture provider 47, github provider 23,
  parity 6, tools 25, smoke 3).
- All five tools drive correctly over **real stdio** via a subprocess MCP client — handshake,
  five tools advertised, one call each, and the error path returning `is_error=true` with the
  actual message rather than a masked one.
- **Live GitHub path confirmed with no credentials**, through the real
  `load_settings → make_provider → tool` chain: unauthenticated reads of
  `modelcontextprotocol/python-sdk`, correct pagination (`has_more=true`) and PR exclusion on
  real data.

**Built**

- `server/`: `config.py`, `errors.py`, `models.py`, `normalize.py`, `tools.py`, `main.py`,
  and `providers/{base,fixture,github}.py`.
- `server/fixtures/`: 13 rows (12 issues + 1 pull request), 5 labels, 2 milestones, comments on
  four issues, plus `README.md` documenting the corpus and the exact `days_since_update` values.
- `docs/inspector-checklist.md`: one example call per tool with expected output, mirroring the
  automated assertions.

**SDK findings — the reason Phase 1 said to check rather than assume.** The installed SDK is
`mcp` 2.1.1 and v1 code does not work against it:

| | |
|---|---|
| `FastMCP` | renamed to `MCPServer` (`mcp.server.mcpserver`); the old module raises with a migration hint |
| Model fields | snake_case — `input_schema`, `output_schema`, `is_error` |
| Bare exceptions | **masked** to `Error executing tool <name>`; only `ToolError` delivers its message to the model |
| Pydantic return type | generates `output_schema` and populates `structured_content`; a bare `dict` gives neither |

Domain errors therefore stay SDK-free in `errors.py` and are converted to `ToolError` at the
tool boundary — one place, and the provider layer stays independently testable.

**Design decisions taken during implementation**

- **Fixtures mirror GitHub's response shape**, so both providers share one `normalize.py`
  conversion path. Parity became structural rather than something a test has to chase; the
  parity test now guards filter/sort/paginate behaviour instead of field mapping.
- **`days_since_update` and `references` are computed server-side.** Staleness questions no
  longer depend on the model doing date arithmetic, and `#N` references are parsed from the
  *untruncated* body so truncation cannot hide a dependency.
- **Rate limits are never slept through.** `RateLimitError` names the reset time; a planner can
  route around a stated failure but not a 40-minute hang.

**Three accuracy bugs found by the smoke run and fixed**

1. The PR-exclusion note claimed "1 pull request excluded" for filters no PR matched. Now
   matching happens first, so the note reports what was actually dropped from *these* results.
2. `get_issue` on a pull-request number said the issue "does not exist". It now says "is a pull
   request, not an issue" — an agent told "does not exist" goes hunting for a typo.
3. The startup banner printed `repo=fixture/local` while the envelope said
   `example/issues-demo`. `Settings.repo_label` was a second source of truth and was removed;
   the provider owns the label.

**New constraint discovered: this network does TLS inspection.** Live calls failed with
`CERTIFICATE_VERIFY_FAILED` because the corporate proxy re-signs certificates with a CA that
`certifi` does not carry. Added opt-in `SSL_TRUST_STORE=system`, which trusts the OS certificate
store via `truststore` (now an explicit dependency — it had only arrived transitively). Left as
opt-in rather than default: changing which CAs are trusted should be a deliberate act. When the
flag is off, the TLS error message names the fix.

**Deferred, unchanged:** `git` (still not installed), `docker` (Phase 7), LLM keys (Phase 3–4),
live repo + PAT / MCP Registry / Hugging Face (second machine).

**Next:** Phase 3 — plan the agent layer: planner/executor loop, the memory schema and its
explicit write rule, and the guardrail checks. Needs an offline stub model, since no LLM keys
exist here.

---

## 2026-08-31 — Session 3: Phase 3 (agent design proposed, awaiting approval)

No agent code written — the runbook gates Phase 4 on approval of this design.

**Deliverable:** `docs/agent-spec.md` — module layout, the `ChatModel` seam, the LangGraph node
graph and state model, budgets, the long-term memory write rule and schema, inbound/outbound
guardrail detectors and actions, config additions, and a test plan.

**Environment findings**

- The full LangGraph stack **resolves on Python 3.14** (dry-run, nothing installed yet):
  `langgraph` 1.2.11, `langgraph-checkpoint-sqlite` 3.1.1, `langchain-core` 1.6.1,
  `aiosqlite` 0.22.1, plus `sqlite-vec` 0.1.9 transitively. 26 packages, no wheel blockers.
- **`langgraph` is 1.x**, and most published examples describe 0.x. Phase 4a's first task is to
  introspect the installed package and record the real API — the `mcp` 1.x→2.x surprise in
  Phase 2 cost enough to make this a standing rule.
- **Ollama is not installed and not running.** The runbook's "dev/offline: local Ollama" fallback
  does not exist on this machine, so the offline path has to be something we build.

**Key design decisions proposed**

- **A `ChatModel` seam mirroring `IssuesProvider`**, with two offline backends: `stub` (a scripted
  planner that drives the real graph, real tool calls, real guardrails — only token generation is
  faked) and `replay` (cassettes recorded from a live provider). Beyond enabling a credential-free
  build, this is what makes the Phase 5 CI gate meaningful: against a live LLM, a regression and a
  sampling roll look identical.
- **The long-term write rule is a five-gate test** (durable, reusable, user-asserted, not
  derivable, atomic+attributable) rather than a heuristic. The *user-asserted* gate is a security
  control: it structurally prevents memory poisoning, since untrusted tool text can never earn a
  persistent write. Facts **supersede** by key rather than accumulate, so memory cannot hold two
  contradictory answers.
- **Guardrails neutralize and annotate; they do not strip.** Fixture issue #7 is a legitimate bug
  report *about* prompt injection, so its body necessarily contains an injection string. An agent
  that deletes matched text cannot answer "what does issue 7 say?" — it destroys the content the
  user asked for. The server labels provenance, the guardrail fences and flags, neither censors.
- **`sqlite-vec` deliberately unused.** Semantic search over a handful of facts is the
  "store everything and hope retrieval sorts it out" design the runbook warns about, and
  non-deterministic recall would break the eval gate.
- **Budgets answer-with-partial on exhaustion** rather than failing or looping, and say why.

**Open for approval:** cassette seam now vs later; keyword vs semantic recall; guardrail action;
and whether the next session does 4a alone or 4a+4b+4c together.

---

## 2026-08-31 — Session 4: Phase 4a (planner/executor loop)

**Decisions approved:** build the cassette seam now; keyword recall; neutralize-and-annotate
guardrails; 4a alone first.

**Verified**

- `pytest` → **228 passed** (server 138 + agent 90: config 15, models 26, nodes 22, graph 17,
  e2e 10).
- The worked example runs over **real stdio** (`python -m agent.demo`), with 2 dependent tool
  calls and a fully cited answer. Traces in `docs/agent-trace.md`.
- Byte-identical answers across repeated runs under `LLM_BACKEND=stub`.

**Built:** `agent/{config,state,prompts,graph,run,demo,mcp_client}.py`,
`agent/models/{base,stub,replay}.py`, `agent/nodes/{plan,execute,synthesize}.py`.

**Two deliberate deviations from the Phase 3 sketch**

1. **Iterative planning** rather than a static `Plan` + `step_index`. The worked example needs
   step 2's args to depend on step 1's result; a static plan cannot express that without
   inventing a template language. `plan_history` also makes a better trace — reasoning per step
   rather than only up front. A test feeds a milestone named `v9-custom` and asserts the planner
   asks for *that*, so the test fails if observations ever stop reaching the planner.
2. **JSON-in-text planner contract** rather than native provider tool-calling. Native calls omit
   the reasoning and differ between Groq and Gemini; one JSON contract is provider-agnostic,
   recordable as a cassette, and carries the `why`.

**Safety behaviour, all traced**

- Budget exhaustion **answers with what it has** and says why. This is why budgets are enforced
  in the `plan` node (a conditional edge cannot record *why* it stopped) and why LangGraph's
  `recursion_limit` is set deliberately *above* `max_steps` — if the framework aborted first,
  the user would get an exception instead of a partial answer.
- The **no-progress detector fires on repetition**, not just on failure. The looping-planner
  trace shows three *successful* identical calls halted at 3 instead of 20; a "stop on repeated
  errors" check would have missed it entirely.
- **Off-allowlist tool calls are refused before the transport**, consume no tool budget, and are
  recorded as structured `GuardrailEvent`s — Phase 5 needs that case countable, not grep-able.
- **Citation containment:** every issue number appearing in an answer must appear in
  `citations`, asserted by test. A referenced-but-unfetched issue is cited as
  "referenced by #3; not independently retrieved" rather than implying it was verified.

**Two environment problems found and fixed**

1. **`StdioToolset` cross-task teardown.** The MCP stdio client uses anyio task groups, which
   require the same task to exit the cancel scope it entered. A yielding pytest fixture tears
   down in a different task and raises *"Attempted to exit cancel scope in a different task"* —
   an error pointing nowhere near the cause. `aclose()` now detects it and raises a message
   naming the fix; e2e tests use `async with` inside the test body.
2. **`pytest` exited 1 with every test passing.** Default `basetemp` keeps a `pytest-current`
   junction under the user TEMP whose cleanup raises `PermissionError [WinError 5]` on this
   machine. Would have failed CI for no real reason. `pyproject.toml` now pins a repo-local
   `--basetemp`.

**Deferred to 4b/4c:** `agent/memory/`, `agent/guardrails/`,
`nodes/{load_memory,persist}.py`, and the `groq`/`gemini` backends — the seam, the JSON contract
and the cassette recorder are all in place, so wiring a live provider is small once a key exists.
Guessing at an unverified SDK is exactly what the `mcp` 1.x→2.x surprise taught us not to do.

**Next:** Phase 4b — SQLite long-term memory, the five-gate write rule (note the schema
correction already recorded in `docs/agent-spec.md` §4.2: liveness must gate on an `active`
column, because a partial index on `superseded_by IS NULL` cannot perform a supersede at all),
and the two-session recall trace.

---

## 2026-09-01 — Session 5: Phase 4b (memory layer)

**Verified**

- `pytest` → **310 passed** (server 138 + agent 172: memory rules 38, memory store 28,
  agent memory 16, plus the 4a suites).
- **Two-session recall works end to end** (`python -m agent.demo --memory`): session 1 stores
  `priority.milestone=v2`; session 2 on a *new thread*, asking "what should I work on?", recalls
  it and filters `list_issues(milestone=v2)`. `v2` appears nowhere in that question.
- **Memory poisoning blocked.** The planted injection in issue #12's comments produces a
  candidate that gate 3 rejects; zero rows written, and the issue text is still reported.
- Supersession verified with an intact audit trail; short-term thread state resumable.

**Built:** `agent/memory/{schema.sql,rules.py,store.py}`,
`agent/nodes/{load_memory,persist}.py`, `agent/session.py`, plus `agent.demo --memory`.

**Design points**

- **The write rule is a five-gate function**, and every failure is collected so one rejection
  explains everything wrong. Gate 3 (user-asserted) requires the fact's quote to appear verbatim
  in the user's own message — that is what makes memory poisoning structurally impossible rather
  than merely unlikely.
- **The database enforces the rule too.** `CHECK (source IN ('user_asserted','user_confirmed'))`
  means a careless future caller gets an `IntegrityError`, not a silent poisoning regression.
  Verified: SQLite rejects the insert, not our Python.
- **Gate 2 is an allowlist of namespaces**, not a heuristic — reusability is not decidable from a
  string, so the design decides in advance which subjects are worth persisting.
- **`persist` runs after `synthesize`**, so a failed run leaves no facts behind.
- **`sqlite-vec` deliberately unused.** Semantic recall over a handful of facts is the
  "persist everything and hope retrieval sorts it out" design the runbook warns about, and
  non-deterministic recall would break the Phase 5 gate.

**Three bugs found and fixed**

1. **`tokenize` could not match a dotted key against plain words.** `convention.branch` was a
   single token, so "what is our branch convention?" shared nothing with its own key — keyword
   recall was effectively broken, hidden by the always-consider rule for `priority` facts. Now
   dotted/hyphenated tokens also yield their parts.
2. **Synthesis claimed to use facts it had not used.** Since priority facts always surface, an
   unrelated question produced "Using your remembered priority.milestone = v2" — a false claim
   about our own reasoning. A fact is now only mentioned if its value reached a tool call, which
   required rendering tool `args` into the observation prompt (worth doing regardless).
3. **`pytest` temp dirs are unusable on this machine in both configurations.** The default keeps a
   `pytest-current` junction whose cleanup raises `PermissionError [WinError 5]`; the
   `--basetemp` workaround added in session 4 fails the same way, because a repo-local dir gets
   wiped at session start while the IDE's file watcher holds it. The suite now uses its own
   `tmp_dir` fixture (`tempfile.TemporaryDirectory`) and never requests `tmp_path`, so neither
   pytest cleanup path runs. `--basetemp` removed; the config stays portable.

**Environment note.** langgraph warned "Deserializing unregistered type … will be blocked in a
future version" for every state model. `agent/session.py` registers them with
`JsonPlusSerializer(allowed_msgpack_modules=…)` so a langgraph upgrade cannot quietly break thread
resume. `from_conn_string()` accepts no `serde`, so the connection is opened directly.

**Next:** Phase 4c — inbound/outbound guardrails. Neutralize-and-annotate (approved), scanning
exactly the fields in `UNTRUSTED_FIELDS`, with every firing logged as a countable event.

---

## 2026-09-01 — Session 6: Phase 4c (guardrails). Phase 4 complete.

**Verified**

- `pytest` → **393 passed** (guardrails 68, agent guardrails 15, plus the earlier suites).
- **False-positive sweep is clean:** 10 benign issues, all labels, all milestones and every
  `list_issues` title produce **zero** detections. Only the two planted payloads flag.
- Both planted payloads caught, annotated, logged and persisted; the answer still reports the
  issue. `python -m agent.demo --guardrails`, trace in `docs/agent-trace.md` §7.
- A model that *obeys* the injection is blocked at the outbound boundary, with the event recorded.

**Built:** `agent/guardrails/{detectors,inbound,outbound}.py`, `agent/nodes/guard_outbound.py`,
the `guardrail_events` table with per-detector counts, `GUARDRAIL_MODE=enforce|report`.

**Design points**

- **Proximity, not mention** — the decision that makes this usable. The corpus openly discusses
  secret handling and prompt injection (#5 is a real report about committed `.env` files, #7's own
  title names injection), so a detector keying on the presence of `.env` would flag most of the
  repository. Detectors require an imperative verb near the sensitive object. The false-positive
  sweep is asserted by test and matters as much as catching the payloads: an over-eager guardrail
  escalates ordinary issues and trains the operator to ignore the log.
- **Annotate, never strip.** Field text is left byte-identical (asserted). Issue #7 is a bug report
  *about* injection, so stripping matched text would make "what does issue 7 say?" unanswerable.
  The envelope gains a `guardrail` block; the prompt gets an `<untrusted-content-warning>` in
  prose, because a structured annotation buried in JSON is easy for a model to skim past.
- **Every detection in #12 is in a comment, not the body.** An agent scanning only bodies would
  pass a one-payload suite and fail in reality — which is why the payload was planted there.
- **Outbound compares against real `os.environ` values**, not only patterns, because pattern lists
  always lag new credential formats. Credential shapes are redacted (the rest of the answer is
  still useful); compliance with a flagged injection is blocked outright.
- **`GUARDRAIL_MODE=report`** records identical events while changing nothing, so Phase 5 can tell
  "the guardrail worked" from "the model was never tempted".

**Two accuracy fixes made during implementation**

1. **Overlapping detections inflated the headline count.** Both `exfiltration` rules matched the
   same "POST … to https://…" phrase, reporting 9 detections where there were 8. Overlaps within a
   family now merge; cross-family overlaps are kept, because five distinct families really fired.
   An inflated number on a résumé is a dishonest one.
2. **The refusal echoed the attacker's host back to the user.** Reproducing attacker-controlled
   text in a user-facing answer puts it somewhere a UI may hyperlink it, for no benefit. The
   sentence now says "an external address"; the exact host goes to the event log and the table.

**Note on the metric.** `guardrail_counts()` returns **detections**, not attacks — one planted
comment accounts for all eight. Phase 7's README must say so rather than inflating it.

**Next:** Phase 5 — promptfoo eval suite (≥20 cases across normal / injection / edge) and the CI
workflow. The suite and local pass rates are fully doable offline; **`git` is still not installed**,
so the GitHub Actions workflow can be written but not run. Phases 6–7 need accounts and Docker, so
they move to the second machine.

### Addendum — verification pass on the Phase 3 design

Corrects this entry's "dry-run, nothing installed yet". The LangGraph stack is now **installed and
probed**, and the proposed memory schema was **tested against SQLite** before anything gets built
on it. Two concrete outcomes:

**1. LangGraph 1.x API verified — the flagged Phase 4a task is done.** Core surface is unchanged
from the 0.x material: `StateGraph`, `add_node`/`add_edge`/`add_conditional_edges`, and
`Annotated[list, operator.add]` reducers all behave as expected. Thread resume verified against a
real checkpointer. Two things that would have bitten:

- **`recursion_limit` is not a `compile()` argument** — it is invoke-time config. So our own
  `max_steps` budget must be the limit that fires, with LangGraph's set above it; otherwise the
  framework aborts first and "answer with what you have" never runs.
- **`AsyncSqliteSaver.from_conn_string()` is an async context manager**, not a constructor. So
  `build_graph()` returns an *uncompiled* graph and compilation happens inside a `run()` helper
  that owns the saver's lifetime.

**2. The proposed `facts` schema could not supersede — fixed.** `CREATE UNIQUE INDEX facts_live
ON facts(key, scope) WHERE superseded_by IS NULL` deadlocks in both orderings: inserting the new
row first violates the unique index (old row still live), and retiring the old row first needs the
new row's id, which does not exist yet. With `foreign_keys` **off** — SQLite's default — that
second update is instead accepted silently, leaving a dangling reference, which is worse than
failing. Liveness now gates on an explicit `active` column; retire → insert → link is verified to
work with one live row enforced and the audit trail intact.

Also added `CHECK (source IN ('user_asserted','user_confirmed'))`, which makes the *user-asserted*
security gate structural: SQLite rejects `source='tool_result'` outright, so memory poisoning is
blocked by the database rather than by our own diligence. Verified.

**Note on concurrency:** `docs/agent-spec.md` and the Session 3 entry above were authored by a
different session than this addendum. The design was left intact and amended in place, not
rewritten.

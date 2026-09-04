# Eval suite

**25 cases, 3 categories, 100% passing. No credentials, no network, deterministic.**

| category | cases | what it checks |
|---|---|---|
| `normal` | 8 | multi-step planning, dependent tool calls, citation completeness, cross-session recall |
| `injection` | 8 | payloads in issue bodies, comments and label descriptions; memory poisoning; outbound compliance |
| `edge` | 9 | missing issue, pull request, empty repo, no search results, refused tool, exhausted budget, looping planner, unparseable model output |

## Running it

```powershell
# the authoritative gate -- this is what CI runs
.venv\Scripts\python.exe -m evals.runner

# one category, or one case, while iterating
.venv\Scripts\python.exe -m evals.runner --category injection
.venv\Scripts\python.exe -m evals.runner --case inject-comment-exfiltration

# machine-readable
.venv\Scripts\python.exe -m evals.runner --json
```

Exit code is non-zero if any case fails **or** if a gated category regressed below
`baseline.json`.

## Why two runners

`runner.py` is authoritative and is what CI gates on: pure Python, no npm, no network, no
credentials, so a cold CI checkout can run it. `promptfooconfig.yaml` exists for promptfoo's
richer local reporting and side-by-side views, which the runbook asks for:

```powershell
cd evals
npx promptfoo@latest eval -c promptfooconfig.yaml
npx promptfoo@latest view
```

`cases.yaml` is the single source of truth for what is tested; the promptfoo config is a curated
subset for the UI. Both drive the same agent through `promptfoo_provider.py`.

**No API key is needed for either.** promptfoo usually wants `OPENAI_API_KEY` for its
`llm-rubric` assertions; this config uses only deterministic assertions
(`contains` / `not-contains` / `javascript`) so there is nothing to configure and nothing to pay
for.

## Why the numbers are trustworthy

Everything runs against the committed JSON corpus (`ISSUES_BACKEND=fixture`) and the scripted
model (`LLM_BACKEND=stub`), with `FIXTURE_NOW` pinned to `2026-08-01T00:00:00Z`.

That is the whole point. A pass rate measured against a live LLM moves on every sampling roll, so
a genuine regression and an unlucky coin flip look identical — you cannot gate CI on it. Pinned
model output means the number only moves when *our* code moves.

What this suite therefore does **not** measure: whether a real model chooses the right tools.
That is what the `replay` backend is for — record cassettes once against Groq on a machine that
has a key (`LLM_BACKEND=groq RECORD_CASSETTES=1`), commit them, and CI replays real model
behaviour with no key and no variance.

## The regression gate

`baseline.json` holds the committed pass rates. `GATED_CATEGORIES` in `runner.py` is currently
`("injection",)`: only a **drop** in injection defence fails the build, and improvements never
fail. Regenerate deliberately, and review the diff:

```powershell
.venv\Scripts\python.exe -m evals.runner --write-baseline
```

The injection category is the one gated because it is the only number where a silent regression
means the agent became easier to hijack.

## Adding a case

Append to `cases.yaml`. Assertion keys are documented at the top of that file and implemented in
`_check()` in `runner.py`. A case needs `id`, `category`, `question`, and an `expect` block.

Optional per-case overrides: `model` (`compliant:<answer>`, `rogue:<tool>`, `garbage:`),
`fixture_dir`, `max_steps`, `guardrail_mode`, `preseed_facts`.

**Watch out for `#` in YAML.** An unquoted `#` starts a comment, so
`question: What does issue #3 say?` silently becomes `"What does issue"` — and the case then
passes or fails for entirely the wrong reason. Always quote questions containing `#`.

## Fixtures

- `../server/fixtures/` — the main corpus (12 issues + 1 pull request, 6 labels, 2 milestones),
  including three planted injection payloads. Documented in `server/fixtures/README.md`.
- `fixtures_empty/` — an empty repository, for the edge case an agent is most likely to fumble:
  answering confidently when there is nothing to find.

# Deploying the web application (Phase 7)

The primary zero-cost path is now **[Render Free](https://render.com/docs/free)**. Render can build the committed `Dockerfile`
directly from GitHub, and `render.yaml` supplies the safe offline defaults and health check.

Hugging Face's [current Spaces documentation](https://huggingface.co/docs/hub/spaces-overview)
says CPU Basic has no hourly charge, but creating a new
Docker or Gradio compute Space requires a paid plan. That no longer matches this project's
free-tier-only constraint, so Hugging Face is not the default deployment path.

## What is already complete here

- Starlette application and browser UI
- credential-driven Groq and Gemini model backends
- live GitHub data backend
- per-browser, process-local conversation checkpoints
- browser-scoped long-term facts, so visitors cannot recall one another's preferences
- rate limiting, secret-safe provider errors, and `/api/health`
- non-root Docker image and Render Blueprint
- offline tests and evals; no deployment credentials embedded

## Account handoff

On the other PC, first follow [handoff.md](handoff.md). The only account actions are:

1. push the repository to GitHub;
2. sign in to Render and connect that GitHub repository;
3. optionally add GitHub/Groq/Gemini secrets in Render's dashboard.

## Deploy on Render Free

1. Sign in at <https://dashboard.render.com/>.
2. Select **New → Blueprint** and connect the GitHub repository.
3. Render detects the root `render.yaml`; approve the `live-data-mcp-agent` service.
4. Confirm the compute plan is **Free** before creating it.
5. Wait for `/api/health` to pass, then open the generated `onrender.com` URL.

No keys are required: the deployed app initially uses fixtures plus the deterministic stub. This
is the best portfolio default because it is reproducible and cannot spend API quota.

## Optional live account linking

In **Render → Service → Environment**, set only the integrations you want:

| Kind | Name | Value |
|---|---|---|
| variable | `ISSUES_BACKEND` | `github` |
| variable | `GITHUB_REPO` | `owner/repository` |
| secret | `GITHUB_TOKEN` | optional fine-grained read-only token |
| variable | `LLM_BACKEND` | `groq`, `gemini`, or `auto` |
| secret | `GROQ_API_KEY` | required for Groq or optional half of `auto` |
| secret | `GEMINI_API_KEY` | required for Gemini or optional half of `auto` |
| variable | `GROQ_MODEL` | optional; default `openai/gpt-oss-20b` |
| variable | `GEMINI_MODEL` | optional; default `gemini-2.5-flash` |

`auto` uses Groq first and falls back to Gemini only for transient errors such as rate limiting or
provider outages. It does not hide an invalid key by crossing to the other provider.

After saving environment values, Render redeploys. Verify:

```text
GET https://<your-service>.onrender.com/api/health
```

The response shows backend names and whether at least one live-model key is configured. It never
returns key values.

## Put the deployed URL into project metadata

On the other PC:

```powershell
.venv\Scripts\python.exe scripts\set_identity.py `
    --demo-url https://<your-service>.onrender.com
```

That replaces `<LIVE-DEMO-URL>` in the README. Add the Registry URL separately after publishing.

## Free-tier limits to disclose

- Render Free web services spin down after 15 minutes without inbound traffic; a cold wake can
  take about a minute.
- The free workspace receives 750 instance-hours per month. A single service that sleeps when
  idle normally fits, but additional always-busy free services share that allowance.
- The filesystem is ephemeral. This app deliberately uses `MEMORY_DB=:memory:` in the public
  deployment, so visitor memory disappears on restart rather than leaking into a persistent file.
- Free services are suitable for a portfolio demo, not a production SLA.

## Local Docker verification

Docker is optional on the account-linking PC because Render builds from the Dockerfile. If Docker
is available:

```powershell
docker build -t live-data-mcp-agent .
docker run --rm -p 7860:7860 live-data-mcp-agent
```

Open <http://localhost:7860> and <http://localhost:7860/api/health>.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| deploy health check fails | app did not bind to Render's `PORT` | keep `app.main` as the Docker command; it reads `PORT` |
| live GitHub still shows fixtures | `ISSUES_BACKEND` was not changed | set it to `github` and set `GITHUB_REPO` |
| `CERTIFICATE_VERIFY_FAILED` locally | TLS-inspecting network | set `SSL_TRUST_STORE=system`; do not disable verification |
| live model returns HTTP 401/403 | wrong key or provider entitlement | correct the secret; the key is not logged |
| HTTP 429 | provider free-tier limit | wait for reset, use `auto` with both keys, or use the stub |
| first visit is slow | normal Render Free cold start | wait for the service to wake |

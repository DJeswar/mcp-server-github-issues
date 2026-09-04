# Other-PC handoff: accounts and keys only

The application is built to completion before it leaves this machine. The other PC should not be
used for feature development; it supplies identity, credentials, repository remotes, and hosted
service connections.

## 1. Bootstrap the copied project

Open Windows PowerShell in the project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_other_pc.ps1
```

The script creates `.venv`, installs the verified lockfile, creates `.env` only when missing, and
runs tests plus evals. It never overwrites an existing `.env`.

## 2. Fill identity once

```powershell
.venv\Scripts\python.exe scripts\set_identity.py `
    --github-user DJeswar `
    --name "DJeswar" `
    --email eswarabd33@gmail.com
```

This updates package metadata, GitHub URLs, the Docker label, the license, docs, and workflows in
one pass. Run `scripts\set_identity.py --check` to list anything still waiting for a deployment
or Registry URL.

## 3. Select integrations in `.env`

For a fully live local run:

```dotenv
ISSUES_BACKEND=github
GITHUB_REPO=owner/repository
GITHUB_TOKEN=

LLM_BACKEND=auto
GROQ_API_KEY=
GEMINI_API_KEY=
```

- A public repository can leave `GITHUB_TOKEN` blank; a read-only fine-grained token increases
  GitHub's rate limit.
- `auto` accepts either model key. With both, Groq is primary and Gemini is the transient fallback.
- Keep real values only in `.env` or the hosting dashboard's secret fields. `.env` is ignored by
  Git and excluded from the Docker build context.

Validate names and key presence without sending a request or printing secrets:

```powershell
.venv\Scripts\python.exe scripts\preflight.py --profile live
```

Then make one intentional live smoke request:

```powershell
.venv\Scripts\python.exe -m agent.demo "Which labels exist in this repo?"
.venv\Scripts\python.exe -m app.main
```

## 4. Link GitHub

```powershell
git init
git add -A
git commit -m "Complete Live-Data MCP Agent"
git branch -M main
git remote add origin https://github.com/DJeswar/mcp-server-github-issues.git
git push -u origin main
```

Authenticate with Git Credential Manager or GitHub CLI when prompted. Do not put a token in the
remote URL.

## 5. Link hosting and publishing accounts

- Deploy the web app: [deploy.md](deploy.md) — connect the GitHub repository to Render.
- Publish PyPI + MCP Registry: [publishing.md](publishing.md).
- Optional third-party listings: [listings.md](listings.md).

After each URL exists:

```powershell
.venv\Scripts\python.exe scripts\set_identity.py `
    --demo-url https://<your-service>.onrender.com `
    --registry-url https://registry.modelcontextprotocol.io/<your-listing>

.venv\Scripts\python.exe scripts\preflight.py --profile release
```

## What remains account-bound

Only these actions cannot be completed safely on the build PC:

- authenticate and push to your GitHub repository;
- connect GitHub to Render and create the Free service;
- create/paste provider API keys if live mode is desired;
- configure PyPI Trusted Publishing and publish the package;
- publish the MCP Registry entry and paste the final URLs.

No application code should need to change for those actions.

# Publishing to the MCP Registry (Phase 6)

Verified against the official docs on **2026-09-01**. The registry is in preview and this flow has
changed before — re-check [modelcontextprotocol.io/registry/quickstart](https://modelcontextprotocol.io/registry/quickstart)
before you run it.

> **Everything in this document needs accounts, so none of it has been executed.** The files it
> refers to (`server.json`, `pyproject.toml`, the `mcp-name:` marker in `README.md`) are written
> and consistent with each other. What is left is genuinely only the credential steps, each marked
> **`>>> YOU DO THIS <<<`**.

---

## What you need

| | Why | Cost |
|---|---|---|
| **GitHub account** | authenticates you to the registry for the `io.github.<you>/*` namespace | free |
| **PyPI account** | the registry stores metadata only — the package itself lives on PyPI | free |
| `mcp-publisher` CLI | publishes `server.json` | free |
| `git` | push tags and releases; installed on the build machine | free |

No paid tier anywhere in this flow.

---

## Step 0 — Fill in your identity

Every placeholder lives in one of a handful of files. Replace them all at once:

```powershell
python scripts/set_identity.py --github-user my-username --name "My Name" --email me@example.com
python scripts/set_identity.py --check    # confirms nothing was missed
```

This rewrites `pyproject.toml`, `server.json`, `README.md`, `app/index.html` and the docs.

**Three names must agree, and the registry rejects the publish if they do not:**

| Where | Value | Must equal |
|---|---|---|
| `server.json` → `name` | `io.github.<you>/github-issues` | the `mcp-name:` marker in `README.md` |
| `README.md` → `<!-- mcp-name: … -->` | `io.github.<you>/github-issues` | `server.json` → `name` |
| `server.json` → `packages[0].identifier` | `mcp-server-github-issues` | `pyproject.toml` → `name` |

The `io.github.` prefix is not decorative: with GitHub authentication the registry only lets you
publish names under `io.github.<your-username>/`.

---

## Step 1 — Check the PyPI name is free

**`>>> YOU DO THIS <<<`** Open <https://pypi.org/project/mcp-server-github-issues/>.

- **404** → the name is free, continue.
- **A project exists** → pick another name, then update **both** `pyproject.toml` → `name` and
  `server.json` → `packages[0].identifier`. They must match.

---

## Step 2 — Build the distribution

No credentials needed. Run this on the build machine to confirm it packages cleanly:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade build twine
.venv\Scripts\python.exe -m build
.venv\Scripts\python.exe -m twine check dist/*
```

You should get `dist/mcp_server_github_issues-0.1.0-py3-none-any.whl` and a `.tar.gz`.

Sanity-check that the fixture corpus made it into the wheel — without it the published server
cannot run credential-free, which is most of its appeal:

```powershell
.venv\Scripts\python.exe -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('dist/*.whl')[0]); print([n for n in z.namelist() if 'fixtures' in n])"
```

---

## Step 3 — Configure secretless PyPI publishing

**`>>> YOU DO THIS — needs your PyPI and GitHub accounts <<<`**

1. Create/sign in to PyPI: <https://pypi.org/account/register/>.
2. Open <https://pypi.org/manage/account/publishing/> and add a **pending GitHub publisher**:
   package `mcp-server-github-issues`, your GitHub owner, repository
   `mcp-server-github-issues`, workflow `publish.yml`, environment `pypi`.
3. In GitHub, create the `pypi` Environment and require your manual approval for deployment.
4. Also create an `mcp-registry` Environment with manual approval.
5. Push a version tag after all tests are green:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The workflow builds once, uploads that exact artifact to PyPI with short-lived OIDC credentials,
then publishes `server.json` to the MCP Registry with GitHub OIDC. There is no PyPI token or MCP
Registry token to create, paste, store, or rotate.

Manual `twine upload` remains a fallback if Trusted Publishing cannot be configured. In that
case create a project-scoped PyPI token only when needed, let Twine prompt for it, and never put
it in `.env` or repository secrets:

```powershell
.venv\Scripts\python.exe -m twine upload dist/*
```

Verify: <https://pypi.org/project/mcp-server-github-issues/>

### Ownership verification — the step people miss

The registry proves you own the PyPI package by looking for the literal string
`mcp-name: <your server name>` **in the package README**, which becomes the PyPI project
description. `README.md` already carries it as an HTML comment (PyPI preserves comments):

```markdown
<!-- mcp-name: io.github.DJeswar/github-issues -->
```

If you renamed the server, that marker must change too, and you must **re-upload to PyPI** —
the registry reads the published description, not your working copy.

---

## Step 4 — Install `mcp-publisher`

No credentials. On Windows:

```powershell
$arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }
Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"
tar xf mcp-publisher.tar.gz mcp-publisher.exe
Remove-Item mcp-publisher.tar.gz
.\mcp-publisher.exe --help
```

macOS/Linux: `brew install mcp-publisher`, or the tarball from the same releases page.

`mcp-publisher.exe` is already in `.gitignore` — do not commit the binary.

---

## Step 5 — Authenticate manually (fallback)

**`>>> YOU DO THIS — needs your GitHub account <<<`**

```powershell
.\mcp-publisher.exe login github
```

It prints a device code and a URL. Open <https://github.com/login/device>, enter the code,
authorise. This is GitHub's device flow — **no token is stored in this repo**, and you are not
creating a PAT for it.

---

## Step 6 — Validate/publish manually (fallback)

```powershell
.\mcp-publisher.exe validate server.json
.\mcp-publisher.exe publish server.json
```

Confirm it is live:

```powershell
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.DJeswar/github-issues"
```

**`>>> YOU DO THIS <<<`** Put the resulting URL everywhere with
`scripts\set_identity.py --registry-url https://...`. That listing is the single hardest-to-fake
artefact in this project — a public, timestamped, independently reviewable fact.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Registry validation failed for package` | the `mcp-name:` marker is missing from the **published** PyPI description | fix `README.md`, bump the version, re-upload to PyPI, publish again |
| `You do not have permission to publish this server` | `server.json` → `name` does not start with `io.github.<your-username>/` | correct the name (case matters) |
| `Invalid or expired Registry JWT token` | login expired | `mcp-publisher login github` again |
| `File already exists` from twine | that version is already on PyPI | bump `version` in `pyproject.toml` **and** in `server.json` (twice: top level and `packages[0]`) |

---

## Version bumps, in the four places that must agree

A mismatch here is the most common cause of a rejected publish:

1. `pyproject.toml` → `version`
2. `server.json` → `version`
3. `server.json` → `packages[0].version`
4. `server/__init__.py` → `__version__` (what the running server reports)

---

## Automated publishing (default)

`.github/workflows/publish.yml` is the recommended path. It uses the official PyPA publish action
and MCP Registry GitHub OIDC. Its two publishing jobs are isolated behind separate GitHub
Environments, and neither has a long-lived repository secret.

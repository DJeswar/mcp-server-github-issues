# Secondary listings: mcp.so and smithery.ai

Do these **after** the official MCP Registry publish (`docs/publishing.md`). Both reuse the same
metadata, so there is nothing new to write — only accounts to connect.

Every step here needs an account, so none of it has been executed. Each is marked
**`>>> YOU DO THIS <<<`**.

---

## Shared metadata

Copy-paste values, all already consistent with `server.json` and `pyproject.toml`:

| Field | Value |
|---|---|
| **Name** | GitHub Issues (read-only) |
| **Registry name** | `io.github.DJeswar/github-issues` |
| **PyPI package** | `mcp-server-github-issues` |
| **Repository** | `https://github.com/DJeswar/mcp-server-github-issues` |
| **License** | MIT |
| **Transport** | stdio |
| **Runtime** | Python ≥ 3.10 |
| **Install** | `uvx mcp-server-github-issues` |
| **Categories** | developer-tools, github, project-management |
| **Tags** | github, issues, read-only, guardrails, fixtures |

### Short description (≤ 160 chars)

> Read-only MCP server for a GitHub repository's issues: list, search, full detail with comments,
> labels and milestones. Runs with no credentials.

### Long description

> Exposes one GitHub repository's issues as five read-only MCP tools: `list_issues`, `get_issue`,
> `search_issues`, `list_labels` and `list_milestones`.
>
> Every tool returns the same envelope — `repo`, `backend`, `fetched_at`, `count`, `has_more`,
> `next_page`, `items`, `notes` — so pagination is explicit rather than silently truncated, and
> anything the server did to the data (pull requests excluded, bodies truncated, relevance
> approximated) is reported rather than hidden. Rate-limit exhaustion returns a structured error
> naming the reset time instead of blocking the caller.
>
> It ships a bundled fixture corpus and defaults to it, so `uvx mcp-server-github-issues` works
> immediately with no token. Set `ISSUES_BACKEND=github` and `GITHUB_REPO=owner/name` for live
> data; a token is optional (unauthenticated public reads work at 60 requests/hour).

### Client configuration snippet

Useful for both listings and for anyone's README:

```json
{
  "mcpServers": {
    "github-issues": {
      "command": "uvx",
      "args": ["mcp-server-github-issues"],
      "env": {
        "ISSUES_BACKEND": "github",
        "GITHUB_REPO": "owner/name",
        "GITHUB_TOKEN": "<optional, read-only on Issues>"
      }
    }
  }
}
```

---

## mcp.so

**`>>> YOU DO THIS <<<`**

1. Go to <https://mcp.so> and sign in with GitHub.
2. **Submit** / **Add server**.
3. Paste the repository URL. mcp.so reads `README.md` and `server.json` automatically — which is
   why those two are the ones worth keeping accurate.
4. Fill anything it does not infer from the table above.
5. Confirm the listing renders the tool list correctly, then save the URL.

No API key. No paid tier.

---

## smithery.ai

**`>>> YOU DO THIS <<<`**

1. Go to <https://smithery.ai> and sign in with GitHub.
2. **Deploy** / **Add server** → connect the repository.
3. Smithery may ask for a `smithery.yaml`. If it does, commit this at the repository root:

```yaml
# smithery.yaml — only needed if Smithery asks for it.
startCommand:
  type: stdio
  configSchema:
    type: object
    properties:
      issuesBackend:
        type: string
        enum: [fixture, github]
        default: fixture
        description: fixture needs no credentials; github reads the live API
      githubRepo:
        type: string
        description: "owner/name — required when issuesBackend is github"
      githubToken:
        type: string
        description: Optional read-only PAT. Unauthenticated public reads work at 60 req/hr.
  commandFunction: |
    (config) => ({
      command: 'uvx',
      args: ['mcp-server-github-issues'],
      env: {
        ISSUES_BACKEND: config.issuesBackend || 'fixture',
        ...(config.githubRepo ? { GITHUB_REPO: config.githubRepo } : {}),
        ...(config.githubToken ? { GITHUB_TOKEN: config.githubToken } : {})
      }
    })
```

4. Smithery's hosted runner may need a Docker image instead of `uvx` — if so, point it at the
   image built by `Dockerfile` (see `docs/deploy.md`).

**Flag `githubToken` as a secret in Smithery's UI** so it is never logged. It is marked
`"isSecret": true` in `server.json` for the same reason.

---

## After both are live

Put all three URLs in `README.md`:

```markdown
- MCP Registry: <paste>
- mcp.so: <paste>
- Smithery: <paste>
```

The registry listing is the load-bearing one — public, timestamped and independently
verifiable. The other two are distribution.

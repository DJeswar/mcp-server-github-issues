# Other Computer Setup and Run Guide

Last verified for this project: **2 September 2026**

This is the single reference to use on the other Windows computer. The application code is
already complete. On that computer you only need to:

1. install the prerequisites;
2. copy the project and bootstrap its environment;
3. insert your identity, repository name, and optional API keys;
4. verify and run the application;
5. optionally connect GitHub, Render, PyPI, and the MCP Registry.

You do **not** need to continue feature development there.

---

## Quick completion checklist

- [ ] Python 3.10 or newer is installed and the **py** command works.
- [ ] Git for Windows is installed and the **git** command works.
- [ ] The complete project folder is present on the other computer.
- [ ] The bootstrap script finishes successfully.
- [ ] Your name, email, and GitHub username are applied.
- [ ] Offline mode runs before any API keys are added.
- [ ] Optional live GitHub and model settings are placed only in **.env**.
- [ ] Live preflight passes.
- [ ] The CLI demo and browser application both run.
- [ ] The repository is pushed to GitHub and Actions is green.
- [ ] Optional Render deployment is live.
- [ ] Optional PyPI and MCP Registry publication is complete.

---

## 1. Accounts and software to prepare

### Required for running locally

- Windows 10 or 11.
- [Python](https://www.python.org/downloads/windows/) 3.10 or newer. During installation, enable
  the Python launcher and add Python to PATH.
- [Git for Windows](https://git-scm.com/download/win).
- A browser.
- VS Code is optional.

Open a **new PowerShell window** after installing Python or Git, then verify:

~~~powershell
py --version
git --version
~~~

Do not continue until both commands return versions.

### Accounts used only for live integrations or publication

| Account | Official page | Required? |
|---|---|---|
| GitHub | [Create/sign in](https://github.com/signup) | Required only for pushing and deployment |
| GitHub repository | [Create a repository](https://github.com/new) | Required only for pushing and deployment |
| GitHub fine-grained token | [Official token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) | Optional for public repositories |
| Groq | [Groq API keys](https://console.groq.com/keys) | Optional live model |
| Gemini | [Google AI Studio API keys](https://aistudio.google.com/app/apikey) | Optional live model |
| Render | [Render dashboard](https://dashboard.render.com/) | Optional public deployment |
| PyPI | [Create a PyPI account](https://pypi.org/account/register/) | Optional package publication |
| MCP Registry | [Registry quickstart](https://modelcontextprotocol.io/registry/quickstart) | Optional registry publication |

The application runs in offline mode without any of these API keys.

---

## 2. Copy and open the project

Copy the complete **project_resume** directory to a normal local path, for example:

    C:\dev\project_resume

Do not copy only the Python files. The folder must also contain:

- **agent**
- **app**
- **server**
- **evals**
- **tests**
- **scripts**
- **requirements.lock.txt**
- **.env.example**
- **Dockerfile**
- **render.yaml**
- **server.json**

Open PowerShell and enter the project:

~~~powershell
cd C:\dev\project_resume
Get-Location
~~~

If you chose a different directory, use that path instead.

---

## 3. Bootstrap the Python environment

Allow local scripts only for this PowerShell process:

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
~~~

Run the prepared bootstrap:

~~~powershell
.\scripts\bootstrap_other_pc.ps1
~~~

The script:

- creates **.venv**;
- installs the exact verified dependencies from **requirements.lock.txt**;
- creates **.env** from **.env.example** only if **.env** is missing;
- runs the test suite;
- runs all 25 evaluations.

Expected final text:

    Bootstrap complete.

The first installation can take several minutes. Do not close PowerShell while it is installing
or testing.

Manual verification, if needed:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evals.runner
~~~

Expected project baseline:

- 435 tests collected and covered;
- 25/25 evaluations pass;
- normal 8/8, injection 8/8, edge 9/9.

---

## 4. Apply your identity

In PowerShell, first set temporary convenience variables. Replace the example values:

~~~powershell
$GitHubUser = "your-github-username"
$YourName = "Your Full Name"
$YourEmail = "your-email@example.com"
~~~

Apply them throughout the package metadata, workflows, README, server metadata, license, and UI:

~~~powershell
.\.venv\Scripts\python.exe scripts\set_identity.py --github-user $GitHubUser --name $YourName --email $YourEmail
~~~

Check remaining placeholders:

~~~powershell
.\.venv\Scripts\python.exe scripts\set_identity.py --check
~~~

At this stage it is **normal** for the check to report the live demo URL and MCP Registry URL.
Those URLs do not exist until the later deployment and publication steps. Your GitHub username,
name, and email should no longer be reported.

The identity values are public project metadata. They are not API credentials.

---

## 5. Prove offline mode first

Open the environment file:

~~~powershell
notepad .env
~~~

For the first run, keep these values:

~~~dotenv
ISSUES_BACKEND=fixture
LLM_BACKEND=stub
SSL_TRUST_STORE=certifi
SESSION_COOKIE_SECURE=false
~~~

Save and close Notepad, then run:

~~~powershell
.\.venv\Scripts\python.exe scripts\preflight.py --profile offline
~~~

Expected result:

    profile=offline issues_backend=fixture llm_backend=stub
    PASS

This proves the application itself works before account credentials or network access are
introduced.

---

## 6. Run the application offline

### Run one command-line agent question

~~~powershell
.\.venv\Scripts\python.exe -m agent.demo "Which labels exist in this repo?"
~~~

It should print the answer and the agent trace.

Additional prepared demonstrations:

~~~powershell
.\.venv\Scripts\python.exe -m agent.demo --memory
.\.venv\Scripts\python.exe -m agent.demo --guardrails
~~~

### Run the browser application

~~~powershell
.\.venv\Scripts\python.exe -m app.main
~~~

Keep that PowerShell window open. In the browser, open:

- [Application](http://127.0.0.1:7860/)
- [Health endpoint](http://127.0.0.1:7860/api/health)

You can also verify health from a second PowerShell window:

~~~powershell
Invoke-RestMethod http://127.0.0.1:7860/api/health
~~~

Ask a question in the browser such as:

    Which open issues are high priority?

Stop the server with **Ctrl+C** in its PowerShell window.

If you only want local, credential-free use, setup is complete here. Continue only if you want
live GitHub/model data or public hosting.

---

## 7. Configure live GitHub and model access

### 7.1 Choose the target GitHub repository

Choose a repository whose issues the application should read. Its value must be:

    owner/repository

For example:

    octocat/example-repository

A public repository works without a token, but GitHub applies a smaller unauthenticated rate
limit. A private repository requires a token.

### 7.2 Optional GitHub token

Use a **fine-grained** token:

1. Follow the [GitHub token instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
2. Select only the repository the application needs.
3. Grant read-only access for Issues.
4. Set an expiration.
5. Copy the token once and keep it private.

This token is for reading the GitHub API. It is not needed for Git pushes, which use Git
Credential Manager or GitHub CLI authentication.

### 7.3 Create at least one model key

Choose either provider or both:

- Create a Groq key at [Groq API Keys](https://console.groq.com/keys).
- Create a new Gemini key at [Google AI Studio](https://aistudio.google.com/app/apikey).

With both keys, **auto** uses Groq first and uses Gemini only for transient provider errors.
With one key, **auto** uses the configured provider.

### 7.4 Put values in .env

Open the file:

~~~powershell
notepad .env
~~~

Change only the relevant lines:

~~~dotenv
ISSUES_BACKEND=github
GITHUB_REPO=owner/repository
GITHUB_TOKEN=

SSL_TRUST_STORE=certifi

LLM_BACKEND=auto
GROQ_API_KEY=
GEMINI_API_KEY=

GROQ_MODEL=openai/gpt-oss-20b
GEMINI_MODEL=gemini-2.5-flash

HOST=0.0.0.0
PORT=7860
SESSION_COOKIE_SECURE=false
~~~

Replace **owner/repository** and paste at least one model key after its equals sign. Paste the
optional GitHub token after **GITHUB_TOKEN=**. Do not put spaces around the equals sign.

Never place keys in:

- **.env.example**
- README files
- Python files
- Git remote URLs
- screenshots
- chat messages

The real **.env** is ignored by Git and excluded from the Docker build context.

On a company network that performs TLS inspection, use:

~~~dotenv
SSL_TRUST_STORE=system
~~~

Do not disable certificate verification.

### 7.5 Validate without sending or printing secrets

~~~powershell
.\.venv\Scripts\python.exe scripts\preflight.py --profile live
~~~

Expected result:

    profile=live issues_backend=github llm_backend=auto
    keys_present: groq=True gemini=False (values are never printed)
    PASS

The exact True/False combination depends on which keys you supplied. At least one model key must
be True.

---

## 8. Run and test live mode

Run a deliberate live CLI request:

~~~powershell
.\.venv\Scripts\python.exe -m agent.demo "Which labels exist in this repo?"
~~~

Then run the web application:

~~~powershell
.\.venv\Scripts\python.exe -m app.main
~~~

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

Confirm the health endpoint reports:

- **issues_backend** as **github**;
- **llm_backend** as **auto**, **groq**, or **gemini**;
- **live_model_configured** as true.

The health response never returns the key values.

Optional MCP transport inspection, if Node.js and npm are installed:

~~~powershell
npx @modelcontextprotocol/inspector .venv\Scripts\python.exe -m server.main
~~~

The MCP Inspector command downloads its package if it is not already present.

---

## 9. Create and push the GitHub repository

Skip this section if you only need local use.

PowerShell variables disappear when you close their window. If you opened a new window since
Step 4, set them again before continuing:

~~~powershell
$GitHubUser = "your-github-username"
$YourName = "Your Full Name"
$YourEmail = "your-email@example.com"
~~~

### 9.1 Initialize Git safely

Run from the project root:

~~~powershell
git init
git config user.name $YourName
git config user.email $YourEmail
git branch -M main
~~~

Confirm that the secret file is ignored:

~~~powershell
git check-ignore .env
~~~

The command must print:

    .env

If it prints nothing, stop and do not commit until **.env** is ignored.

Stage the project and inspect it:

~~~powershell
git add -A
git status --short
~~~

Verify that **.env** is not listed. Then commit:

~~~powershell
git commit -m "Complete live-data MCP agent"
~~~

### 9.2 Create the remote repository

1. Open [GitHub New Repository](https://github.com/new).
2. Repository name: **mcp-server-github-issues**.
3. Choose Public for a portfolio repository, or Private if required.
4. Do not add another README, license, or gitignore because the local project already has them.
5. Create the repository.

Connect and push:

~~~powershell
git remote add origin "https://github.com/$GitHubUser/mcp-server-github-issues.git"
git push -u origin main
~~~

Authenticate through Git Credential Manager or GitHub CLI when prompted. Never embed a personal
access token in the remote URL.

### 9.3 Verify GitHub Actions

Open the repository on GitHub and select **Actions**. The **evals** workflow starts on a push to
main and runs:

- unit tests;
- the 25-case evaluation suite.

Wait until both jobs are green. No Groq, Gemini, or personal GitHub token is required for this
workflow.

Do not create the release tag until the main workflow is green.

---

## 10. Deploy the browser application on Render

Skip this section if you only need local use.

The first deployment should use the safe fixture/stub defaults. Add live keys only after that
deployment succeeds.

1. Sign in to the [Render dashboard](https://dashboard.render.com/).
2. Select **New**, then **Blueprint**.
3. Connect the GitHub account and authorize Render for the repository.
4. Select **mcp-server-github-issues**.
5. Render detects **render.yaml** in the repository root.
6. Confirm the service name **live-data-mcp-agent**.
7. Confirm the plan says **Free**.
8. Deploy the Blueprint.
9. Wait until the **/api/health** health check passes.
10. Open the generated **onrender.com** URL.

The first deployed app runs with:

    ISSUES_BACKEND=fixture
    LLM_BACKEND=stub

No key is required for this first proof.

### Add live integrations to Render

In **Render > Service > Environment**, add the values you want:

| Type | Name | Value |
|---|---|---|
| variable | ISSUES_BACKEND | github |
| variable | GITHUB_REPO | owner/repository |
| secret | GITHUB_TOKEN | optional read-only token |
| variable | LLM_BACKEND | auto |
| secret | GROQ_API_KEY | your Groq key, if used |
| secret | GEMINI_API_KEY | your Gemini key, if used |

Render does not read the **.env** file from your other computer. Add hosted secrets through the
Render dashboard, never by committing **.env**.

Save the variables and allow Render to redeploy. Verify:

    https://your-service-name.onrender.com/api/health

Render Free services can sleep when inactive, so the first request after inactivity can be slow.

### Store the final demo URL in project metadata

Set the actual URL:

~~~powershell
$DemoUrl = "https://your-service-name.onrender.com"
.\.venv\Scripts\python.exe scripts\set_identity.py --demo-url $DemoUrl
git add -A
git commit -m "Add live demo URL"
git push
~~~

---

## 11. Optional PyPI and MCP Registry publication

This section completes the publication phase. It is not required merely to run the application.

### 11.1 Check the package name

Open:

[https://pypi.org/project/mcp-server-github-issues/](https://pypi.org/project/mcp-server-github-issues/)

- A 404 means the name is available.
- If another owner already uses it, do not publish or tag. Choose a unique package name and follow
  **docs/publishing.md** to update all matching identifiers.

### 11.2 Configure PyPI Trusted Publishing

1. Sign in to [PyPI](https://pypi.org/).
2. Open [Publishing settings](https://pypi.org/manage/account/publishing/).
3. Add a pending GitHub publisher with:
   - PyPI project: **mcp-server-github-issues**
   - GitHub owner: your GitHub username
   - Repository: **mcp-server-github-issues**
   - Workflow: **publish.yml**
   - Environment: **pypi**
4. In GitHub repository settings, create an Environment named **pypi**.
5. Add manual deployment approval if desired.
6. Create another GitHub Environment named **mcp-registry**.

The workflow uses short-lived OIDC credentials. Do not create a long-lived PyPI repository secret.

### 11.3 Tag the release

Before tagging, confirm the version is **0.1.0** in:

1. **pyproject.toml**
2. **server.json** top-level version
3. **server.json** package version
4. **server/__init__.py**

Then:

~~~powershell
git status
git tag v0.1.0
git push origin v0.1.0
~~~

Open GitHub Actions and follow the **publish** workflow. Approve the **pypi** and
**mcp-registry** environments when prompted.

The workflow:

1. reruns tests and evaluations;
2. builds and validates the wheel and source archive;
3. publishes to PyPI;
4. authenticates to the MCP Registry using GitHub OIDC;
5. publishes **server.json**.

Verify the PyPI page and MCP Registry result before continuing.

### 11.4 Save the Registry URL

After the listing exists:

~~~powershell
$RegistryUrl = "https://paste-the-real-registry-listing-url-here"
.\.venv\Scripts\python.exe scripts\set_identity.py --registry-url $RegistryUrl
.\.venv\Scripts\python.exe scripts\preflight.py --profile release
git add -A
git commit -m "Add MCP Registry listing"
git push
~~~

The release preflight should now return **PASS**. If it still lists a placeholder, follow the
reported filename and complete that value.

For manual publishing or troubleshooting, use **docs/publishing.md**.

---

## 12. Normal daily run after setup

You do not rerun the bootstrap every day.

Open PowerShell:

~~~powershell
cd C:\dev\project_resume
.\.venv\Scripts\python.exe scripts\preflight.py --profile live
.\.venv\Scripts\python.exe -m app.main
~~~

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

Stop with **Ctrl+C**.

For offline use instead:

1. set **ISSUES_BACKEND=fixture** and **LLM_BACKEND=stub** in **.env**;
2. use **--profile offline** in the preflight command;
3. run the same application command.

---

## 13. Updating the project later

After pulling a trusted update:

~~~powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evals.runner
~~~

The bootstrap script never overwrites an existing **.env**, but keeping a separate secure backup
of your credentials is still your responsibility.

---

## 14. Troubleshooting

| Problem | What to do |
|---|---|
| **py is not recognized** | Install Python 3.10+ with the launcher enabled, then open a new PowerShell window. |
| PowerShell blocks the bootstrap script | Run **Set-ExecutionPolicy -Scope Process Bypass** in that window and retry. |
| Tests fail during the first bootstrap | Keep the complete output, confirm all project files were copied, and rerun the two manual verification commands. |
| **CERTIFICATE_VERIFY_FAILED** on a company network | Set **SSL_TRUST_STORE=system**. Do not disable TLS verification. |
| GitHub still returns fixture data | Confirm **ISSUES_BACKEND=github**, save **.env**, stop the app, and restart it. |
| GitHub returns 401 or 403 | Correct the token, repository permission, or **owner/repository** value. Public repositories can be tested with a blank token. |
| Groq/Gemini returns 401 or 403 | Create a current key, paste it into the correct **.env** field, and restart the app. |
| Provider returns 429 | The provider quota is exhausted. Wait for reset, use the other provider, or return to **LLM_BACKEND=stub**. |
| Port 7860 is already used | Stop the old process or change **PORT=7861** in **.env**, then open the new port. |
| Render shows fixtures after keys were added | Also set **ISSUES_BACKEND=github**, **GITHUB_REPO**, and a live **LLM_BACKEND** in Render Environment. |
| First Render request is slow | Wait for the free service to wake, then refresh. |
| **.env** appears in **git status** after staging | Unstage it immediately with **git restore --staged .env** and confirm **git check-ignore .env** prints the filename. |
| A key was accidentally committed or shared | Revoke it at the provider immediately, create a new key, then remove the leaked value from Git history before pushing further. |

---

## 15. Final success criteria

The transfer is complete when all applicable statements are true:

- Offline preflight passes.
- The command-line demo answers a fixture question.
- The browser opens locally and **/api/health** returns status **ok**.
- Live preflight passes after you add the selected accounts.
- A live question reports the GitHub and model backends you selected.
- **.env** is ignored and never appears in GitHub.
- GitHub Actions tests and evaluations are green.
- Optional Render URL opens and passes its health check.
- Optional PyPI package and MCP Registry listing are public.
- Release preflight passes after both public URLs are stored.

For deeper details, consult:

- **docs/handoff.md**
- **docs/deploy.md**
- **docs/publishing.md**
- **docs/status.md**

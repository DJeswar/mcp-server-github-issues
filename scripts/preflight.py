"""Validate an offline, live, or release setup without printing secret values."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.config import load_agent_settings
from server.config import load_settings

from scripts.set_identity import find_placeholders

REQUIRED = (
    "Dockerfile",
    "render.yaml",
    "requirements.lock.txt",
    "server.json",
    "LICENSE",
    "app/main.py",
    "agent/models/live.py",
)


def _configuration_summary() -> tuple[str, str, bool, bool]:
    agent = load_agent_settings()
    server = load_settings()
    return (
        agent.llm_backend,
        server.backend,
        bool(agent.groq_api_key),
        bool(agent.gemini_api_key),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("offline", "live", "release"), default="offline"
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    for relative in REQUIRED:
        if not (REPO_ROOT / relative).is_file():
            failures.append(f"missing required file: {relative}")

    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=True)

    try:
        llm, issues, has_groq, has_gemini = _configuration_summary()
    except Exception as exc:
        failures.append(f"configuration error: {exc}")
        llm, issues, has_groq, has_gemini = "invalid", "invalid", False, False

    if args.profile == "live":
        if not env_path.is_file():
            failures.append("live profile requires .env (copy .env.example first)")
        if issues != "github":
            failures.append("live profile requires ISSUES_BACKEND=github")
        if llm not in ("groq", "gemini", "auto"):
            failures.append("live profile requires LLM_BACKEND=groq, gemini, or auto")
        if not (has_groq or has_gemini):
            failures.append("live profile requires at least one model API key")

    if args.profile == "release":
        for relative, tokens in find_placeholders().items():
            failures.append(f"identity placeholder in {relative}: {', '.join(tokens)}")
        if shutil.which("git") is None:
            failures.append("git is required for the release profile")

    print(f"profile={args.profile} issues_backend={issues} llm_backend={llm}")
    print(f"keys_present: groq={has_groq} gemini={has_gemini} (values are never printed)")
    if failures:
        print("FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

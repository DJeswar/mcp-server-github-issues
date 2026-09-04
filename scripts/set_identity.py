"""Replace the identity placeholders across the project in one pass.

Every file that needs your GitHub username, name or email carries the literal placeholders
`YOUR-GITHUB-USERNAME`, `YOUR-HF-USERNAME`, `YOUR NAME` and `you@example.com`. Hunting them by hand is how one gets
missed and a publish fails halfway. Run this on the machine with your accounts:

    python scripts/set_identity.py --github-user my-username --hf-user my-hf-name \
        --name "My Name" --email me@example.com

    python scripts/set_identity.py --check          # list remaining placeholders
    python scripts/set_identity.py --github-user x --dry-run

It rewrites files in place. Review with `git diff` before committing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDERS = {
    "github_user": "YOUR-GITHUB-USERNAME",
    "hf_user": "YOUR-HF-USERNAME",
    "name": "YOUR NAME",
    "email": "you@example.com",
    "demo_url": "<LIVE-DEMO-URL>",
    "registry_url": "<MCP-REGISTRY-URL>",
}

#: Files that carry placeholders. Kept explicit rather than globbing the tree, so this script
#: cannot wander into .venv, fixtures or the docs' example snippets.
TARGETS = (
    "pyproject.toml",
    "server.json",
    "README.md",
    "docs/publishing.md",
    "docs/deploy.md",
    "docs/listings.md",
    "app/index.html",
    "Dockerfile",
    "LICENSE",
    ".github/workflows/publish.yml",
    ".github/workflows/evals.yml",
    "docs/handoff.md",
)


def _validate(kind: str, value: str) -> str:
    value = value.strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{kind.replace('_', ' ')} cannot be blank or contain newlines")
    if kind == "github_user":
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value):
            raise ValueError("GitHub username must be 1-39 letters, digits or hyphens")
    elif kind == "hf_user":
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,94}[A-Za-z0-9])?", value):
            raise ValueError("Hugging Face username contains unsupported characters")
    elif kind == "email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("email must look like name@example.com")
    elif kind in ("demo_url", "registry_url"):
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"{kind.replace('_', ' ')} must be an https URL")
    return value


def find_placeholders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for relative in TARGETS:
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        hits = [token for token in PLACEHOLDERS.values() if token in text]
        if hits:
            found[relative] = hits
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-user", help="your GitHub username (lowercase)")
    parser.add_argument("--hf-user", help="your Hugging Face username")
    parser.add_argument("--name", help="your display name, for package metadata")
    parser.add_argument("--email", help="your contact email, for package metadata")
    parser.add_argument("--demo-url", help="deployed Hugging Face Space URL")
    parser.add_argument("--registry-url", help="published MCP Registry listing URL")
    parser.add_argument("--check", action="store_true", help="only report what is unreplaced")
    parser.add_argument("--dry-run", action="store_true", help="show changes without writing")
    args = parser.parse_args(argv)

    if args.check or not any(
        (
            args.github_user,
            args.hf_user,
            args.name,
            args.email,
            args.demo_url,
            args.registry_url,
        )
    ):
        remaining = find_placeholders()
        if not remaining:
            print("No placeholders left. Ready to publish.")
            return 0
        print("Placeholders still present:\n")
        for relative, tokens in sorted(remaining.items()):
            print(f"  {relative}")
            for token in tokens:
                print(f"      {token}")
        print(
            "\nRun with --github-user / --hf-user / --name / --email, then add "
            "--demo-url / --registry-url after those URLs exist."
        )
        return 1

    replacements: dict[str, str] = {}
    for kind, value in (
        ("github_user", args.github_user),
        ("hf_user", args.hf_user),
        ("name", args.name),
        ("email", args.email),
        ("demo_url", args.demo_url),
        ("registry_url", args.registry_url),
    ):
        if value:
            try:
                replacements[PLACEHOLDERS[kind]] = _validate(kind, value)
            except ValueError as exc:
                parser.error(str(exc))

    changed = 0
    for relative in TARGETS:
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = original
        for token, value in replacements.items():
            updated = updated.replace(token, value)
        if updated == original:
            continue
        changed += 1
        if args.dry_run:
            print(f"would update {relative}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"updated {relative}")

    if not changed:
        print("Nothing to change.")
    elif not args.dry_run:
        print(f"\n{changed} file(s) updated. Review with `git diff`, then:")
        print("  python scripts/set_identity.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

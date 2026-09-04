"""Release descriptors and the other-PC handoff remain safe and internally consistent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts.set_identity import PLACEHOLDERS, TARGETS, _validate

ROOT = Path(__file__).resolve().parent.parent


def test_render_blueprint_is_free_docker_with_health_check():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["plan"] == "free"
    assert service["healthCheckPath"] == "/api/health"


def test_render_blueprint_contains_no_secret_values():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in text
    assert "GEMINI_API_KEY" not in text
    assert "GITHUB_TOKEN" not in text


def test_every_identity_target_exists():
    missing = [relative for relative in TARGETS if not (ROOT / relative).is_file()]
    assert missing == []


@pytest.mark.parametrize(
    "kind,value",
    [
        ("github_user", "valid-user"),
        ("hf_user", "valid_user"),
        ("name", "A Person"),
        ("email", "person@example.com"),
        ("demo_url", "https://demo.onrender.com"),
        ("registry_url", "https://registry.modelcontextprotocol.io/example"),
    ],
)
def test_identity_values_are_validated(kind, value):
    assert _validate(kind, value) == value


@pytest.mark.parametrize(
    "kind,value",
    [
        ("github_user", "-invalid"),
        ("email", "not-an-email"),
        ("demo_url", "http://insecure.example"),
        ("registry_url", "javascript:alert(1)"),
    ],
)
def test_invalid_identity_values_are_rejected(kind, value):
    with pytest.raises(ValueError):
        _validate(kind, value)


def test_license_is_real_and_identity_driven():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert PLACEHOLDERS["name"] in text
    assert re.search(r"Permission is hereby granted", text)


def test_env_example_documents_live_models_without_keys():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "GROQ_MODEL=openai/gpt-oss-20b" in text
    assert "GEMINI_MODEL=gemini-2.5-flash" in text
    assert "not implemented yet" not in text


def test_publish_workflow_uses_short_lived_oidc_not_repository_tokens():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "mcp-publisher login github-oidc" in text
    assert "mcp-publisher validate server.json" in text
    assert "PYPI_API_TOKEN" not in text
    assert "${{ secrets." not in text

"""Public web boundary: health, per-browser sessions, and current-turn traces."""

from __future__ import annotations

from starlette.testclient import TestClient

import app.main as web
from app.main import SESSION_COOKIE, app


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("LLM_BACKEND", "stub")
    monkeypatch.setenv("ISSUES_BACKEND", "fixture")
    monkeypatch.setenv("MEMORY_DB", ":memory:")
    return TestClient(app)


def test_homepage_sets_an_http_only_session_cookie(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_health_discloses_configuration_without_secrets(monkeypatch):
    with _client(monkeypatch) as client:
        payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["llm_backend"] == "stub"
    assert payload["live_model_configured"] is False
    assert "api_key" not in payload


def test_app_explicitly_forwards_live_backend_environment(monkeypatch):
    seen = {}

    class CapturingToolset:
        def __init__(self, *, env):
            seen.update(env)

    monkeypatch.setattr(web, "InProcessToolset", CapturingToolset)
    monkeypatch.setenv("ISSUES_BACKEND", "github")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    web._toolset_from_environment()
    assert seen["ISSUES_BACKEND"] == "github"
    assert seen["GITHUB_REPO"] == "owner/repo"


def test_second_question_has_only_its_own_plan_and_tool_calls(monkeypatch):
    with _client(monkeypatch) as client:
        first = client.post("/api/ask", json={"question": "What does issue #3 say?"})
        second = client.post(
            "/api/ask", json={"question": "Which labels exist in this repo?"}
        )
    assert first.status_code == second.status_code == 200
    assert [call["tool"] for call in first.json()["tool_calls"]] == ["get_issue"]
    assert [call["tool"] for call in second.json()["tool_calls"]] == ["list_labels"]
    assert second.json()["plan"][0]["index"] == 0


def test_long_term_recall_is_isolated_between_browsers(monkeypatch):
    with _client(monkeypatch) as first, _client(monkeypatch) as second:
        stored = first.post(
            "/api/ask",
            json={
                "question": "Let's plan the release. The v2 milestone is our current priority."
            },
        )
        unrelated = second.post(
            "/api/ask", json={"question": "What should I work on?"}
        )
    assert stored.status_code == unrelated.status_code == 200
    assert unrelated.json()["recalled_facts"] == []

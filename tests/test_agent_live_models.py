"""Provider wire contracts, error hygiene, and transient fallback behaviour."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.config import load_agent_settings
from agent.models import make_chat_model
from agent.models.base import Message, ModelResponse
from agent.models.live import FallbackModel, GeminiModel, GroqModel, ModelProviderError

MESSAGES = [
    Message(role="system", content="Return JSON."),
    Message(role="user", content="Plan this."),
    Message(role="assistant", content='{"action":"finish"}'),
]


class TestGroqModel:
    async def test_success_uses_documented_chat_completions_shape(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b",
                    "choices": [{"message": {"content": '{"action":"finish"}'}}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 4},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await GroqModel("groq-secret", client=client).complete(MESSAGES)

        request = seen["request"]
        payload = seen["payload"]
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer groq-secret"
        assert payload["model"] == "openai/gpt-oss-20b"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0] == {"role": "system", "content": "Return JSON."}
        assert response.text == '{"action":"finish"}'
        assert response.usage["prompt_tokens"] == 9

    async def test_tool_choice_conflict_falls_back_to_a_compatible_model(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            seen.append(payload["model"])
            if len(seen) == 1:
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "message": "Tool choice is none, but model called a tool"
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "model": payload["model"],
                    "choices": [{"message": {"content": '{"action":"finish"}'}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await GroqModel("groq-secret", client=client).complete(MESSAGES)

        assert seen == ["openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
        assert response.model == "llama-3.3-70b-versatile"
        assert response.usage["fallback"]["from"] == "openai/gpt-oss-20b"

    async def test_auth_error_is_nonretryable_and_does_not_leak_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": {"message": "invalid key never-print-this"}},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = GroqModel("never-print-this", client=client)
            with pytest.raises(ModelProviderError) as caught:
                await model.complete(MESSAGES)

        assert caught.value.status_code == 401
        assert caught.value.retryable is False
        assert "never-print-this" not in str(caught.value)
        assert "[REDACTED]" in str(caught.value)

    async def test_rate_limit_is_retryable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": {"message": "slow down"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ModelProviderError) as caught:
                await GroqModel("x", client=client).complete(MESSAGES)
        assert caught.value.retryable is True


class TestGeminiModel:
    async def test_success_maps_roles_and_json_generation_config(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "modelVersion": "gemini-2.5-flash",
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"thought": True, "text": "hidden"},
                                    {"text": '{"action":"finish"}'},
                                ]
                            }
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 8},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await GeminiModel("gemini-secret", client=client).complete(MESSAGES)

        request = seen["request"]
        payload = seen["payload"]
        assert str(request.url).endswith("/models/gemini-2.5-flash:generateContent")
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert payload["systemInstruction"]["parts"][0]["text"] == "Return JSON."
        assert [content["role"] for content in payload["contents"]] == ["user", "model"]
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert response.text == '{"action":"finish"}'
        assert response.usage["promptTokenCount"] == 8

    async def test_non_json_text_is_reported_as_retryable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ModelProviderError, match="not a JSON object") as caught:
                await GeminiModel("x", client=client).complete(MESSAGES)
        assert caught.value.retryable is True


class FixedModel:
    def __init__(self, name: str, result: ModelResponse | Exception) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    async def complete(self, messages, tools=None):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class TestFallbackModel:
    async def test_transient_primary_failure_uses_secondary(self):
        primary = FixedModel("groq", ModelProviderError("groq", "busy", retryable=True))
        secondary = FixedModel(
            "gemini", ModelResponse(text='{"action":"finish"}', model="gemini")
        )
        result = await FallbackModel(primary, secondary).complete(MESSAGES)
        assert (primary.calls, secondary.calls) == (1, 1)
        assert result.usage["fallback"]["from"] == "groq"

    async def test_auth_failure_does_not_cross_provider_boundary(self):
        primary = FixedModel(
            "groq", ModelProviderError("groq", "bad key", status_code=401)
        )
        secondary = FixedModel(
            "gemini", ModelResponse(text='{"action":"finish"}', model="gemini")
        )
        with pytest.raises(ModelProviderError):
            await FallbackModel(primary, secondary).complete(MESSAGES)
        assert secondary.calls == 0

    def test_auto_with_both_keys_builds_fallback(self):
        settings = load_agent_settings(
            {
                "LLM_BACKEND": "auto",
                "GROQ_API_KEY": "g",
                "GEMINI_API_KEY": "m",
            }
        )
        assert isinstance(make_chat_model(settings), FallbackModel)

    def test_auto_with_one_key_uses_that_provider(self):
        settings = load_agent_settings(
            {"LLM_BACKEND": "auto", "GEMINI_API_KEY": "m"}
        )
        assert isinstance(make_chat_model(settings), GeminiModel)

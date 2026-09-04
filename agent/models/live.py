"""Credential-driven Groq and Gemini model backends.

Both providers use their documented HTTPS APIs through ``httpx``.  Keeping the transport here
avoids an SDK dependency whose major version can drift between the build and account-linking
machines.  The rest of the agent still sees the same small ``ChatModel`` contract.

Secrets are used only in request headers.  They are never included in exception messages,
responses, traces, or cassettes.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from .base import ChatModel, Message, ModelOutputError, ModelResponse, ToolSpec, parse_json_object

GROQ_API_BASE = "https://api.groq.com/openai/v1"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_COMPATIBILITY_MODEL = "llama-3.3-70b-versatile"


class ModelProviderError(Exception):
    """A live provider failed without exposing credentials or full response bodies."""

    def __init__(
        self,
        provider: str,
        detail: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        status = f" HTTP {status_code}" if status_code is not None else ""
        super().__init__(f"{provider}{status}: {detail}")


def _verify_for(ssl_trust: str) -> Any:
    if ssl_trust != "system":
        return True

    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _network_detail(exc: Exception, ssl_trust: str) -> str:
    detail = str(exc) or type(exc).__name__
    if "CERTIFICATE_VERIFY_FAILED" in detail and ssl_trust != "system":
        detail += (
            " -- behind a TLS-inspecting corporate proxy, set "
            "SSL_TRUST_STORE=system to use the operating system certificate store"
        )
    return detail[:500]


def _error_detail(response: httpx.Response) -> str:
    """Extract a useful provider message without returning an arbitrary response body."""
    try:
        payload = response.json()
    except ValueError:
        return (response.reason_phrase or "request failed")[:300]

    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("status")
            if message:
                return str(message)[:300]
        if isinstance(error, str):
            return error[:300]
        if message := payload.get("message"):
            return str(message)[:300]
    return "provider rejected the request"


def _retryable_status(status_code: int) -> bool:
    return status_code in (408, 409, 425, 429) or status_code >= 500


def _redact_values(detail: str, values: tuple[str, ...]) -> str:
    for value in values:
        if value:
            detail = detail.replace(value, "[REDACTED]")
    return detail


class _HttpModel:
    provider: str

    def __init__(
        self,
        *,
        timeout: float,
        ssl_trust: str,
        secret_values: tuple[str, ...] = (),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout
        self._ssl_trust = ssl_trust
        self._secret_values = secret_values
        self._client = client

    async def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    verify=_verify_for(self._ssl_trust),
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                self.provider,
                _redact_values(
                    _network_detail(exc, self._ssl_trust), self._secret_values
                ),
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            raise ModelProviderError(
                self.provider,
                _redact_values(_error_detail(response), self._secret_values),
                status_code=response.status_code,
                retryable=_retryable_status(response.status_code),
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                self.provider,
                "returned a non-JSON response",
                status_code=response.status_code,
                retryable=True,
            ) from exc
        if not isinstance(data, dict):
            raise ModelProviderError(
                self.provider,
                "returned an unexpected response shape",
                status_code=response.status_code,
                retryable=True,
            )
        return data

    def _validated_text(self, text: Any) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ModelProviderError(
                self.provider, "returned no text", retryable=True
            )
        try:
            parse_json_object(text)
        except ModelOutputError as exc:
            raise ModelProviderError(
                self.provider,
                "returned text that was not a JSON object",
                retryable=True,
            ) from exc
        return text


class GroqModel(_HttpModel):
    """Groq Chat Completions using JSON Object Mode."""

    provider = "groq"
    name = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/gpt-oss-20b",
        fallback_model: str = GROQ_COMPATIBILITY_MODEL,
        timeout: float = 30.0,
        max_output_tokens: int = 4096,
        ssl_trust: str = "certifi",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            timeout=timeout,
            ssl_trust=ssl_trust,
            secret_values=(api_key,),
            client=client,
        )
        self._api_key = api_key
        self._model = model
        self._fallback_model = fallback_model
        self._max_output_tokens = max_output_tokens

    def _is_tool_choice_error(self, exc: ModelProviderError) -> bool:
        detail = str(exc).lower()
        return exc.status_code == 400 and (
            "tool choice is none" in detail or "called a tool" in detail
        )

    async def _complete_with_model(
        self, messages: list[Message], model: str
    ) -> ModelResponse:
        data = await self._post(
            f"{GROQ_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload={
                "model": model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "temperature": 0,
                "max_completion_tokens": self._max_output_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        text = self._validated_text(message.get("content"))
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ModelResponse(text=text, model=str(data.get("model") or model), usage=usage)

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        try:
            return await self._complete_with_model(messages, self._model)
        except ModelProviderError as exc:
            if self._fallback_model and self._fallback_model != self._model and self._is_tool_choice_error(exc):
                response = await self._complete_with_model(messages, self._fallback_model)
                usage = dict(response.usage)
                usage["fallback"] = {
                    "from": self._model,
                    "to": self._fallback_model,
                    "reason": "groq_tool_choice_conflict",
                }
                return response.model_copy(update={"usage": usage})
            raise


class GeminiModel(_HttpModel):
    """Gemini ``generateContent`` for stateless JSON generation."""

    provider = "gemini"
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.5-flash",
        timeout: float = 30.0,
        max_output_tokens: int = 4096,
        ssl_trust: str = "certifi",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            timeout=timeout,
            ssl_trust=ssl_trust,
            secret_values=(api_key,),
            client=client,
        )
        self._api_key = api_key
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
            for message in messages
            if message.role != "system"
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self._max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        encoded_model = quote(self._model, safe="-._")
        data = await self._post(
            f"{GEMINI_API_BASE}/models/{encoded_model}:generateContent",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            payload=payload,
        )

        candidates = data.get("candidates") or []
        parts = (
            candidates[0].get("content", {}).get("parts", []) if candidates else []
        )
        text = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict) and not part.get("thought")
        )
        text = self._validated_text(text)
        usage = (
            data.get("usageMetadata")
            if isinstance(data.get("usageMetadata"), dict)
            else {}
        )
        model_version = str(data.get("modelVersion") or self._model)
        return ModelResponse(text=text, model=model_version, usage=usage)


class FallbackModel:
    """Use the secondary provider only for transient primary-provider failures."""

    def __init__(self, primary: ChatModel, fallback: ChatModel) -> None:
        self._primary = primary
        self._fallback = fallback
        self.name = f"fallback[{primary.name}->{fallback.name}]"

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> ModelResponse:
        try:
            return await self._primary.complete(messages, tools)
        except ModelProviderError as exc:
            if not exc.retryable:
                raise
            response = await self._fallback.complete(messages, tools)
            usage = dict(response.usage)
            usage["fallback"] = {
                "from": self._primary.name,
                "to": self._fallback.name,
                "reason": "transient_provider_failure",
            }
            return response.model_copy(update={"usage": usage})


__all__ = [
    "FallbackModel",
    "GeminiModel",
    "GroqModel",
    "ModelProviderError",
]

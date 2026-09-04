"""Model backends. `make_chat_model()` is all the graph needs."""

from __future__ import annotations

from server.errors import ConfigError

from ..config import AgentSettings
from .base import ChatModel, Message, ModelOutputError, ModelResponse, ToolSpec
from .live import FallbackModel, GeminiModel, GroqModel, ModelProviderError
from .replay import CassetteMissError, RecordingModel, ReplayModel, cassette_key
from .stub import StubModel


def make_chat_model(settings: AgentSettings) -> ChatModel:
    backend = settings.llm_backend

    if backend == "stub":
        model: ChatModel = StubModel()
    elif backend == "replay":
        model = ReplayModel(settings.cassette_dir)
    elif backend == "groq":
        model = _groq(settings)
    elif backend == "gemini":
        model = _gemini(settings)
    else:
        # auto means Groq primary, Gemini fallback. With only one configured key it degrades to
        # that provider instead of requiring a second account.
        if settings.groq_api_key and settings.gemini_api_key:
            model = FallbackModel(_groq(settings), _gemini(settings))
        elif settings.groq_api_key:
            model = _groq(settings)
        elif settings.gemini_api_key:
            model = _gemini(settings)
        else:  # load_agent_settings normally catches this; keep the factory safe in isolation.
            raise ConfigError("LLM_BACKEND=auto requires at least one live-model API key")

    if settings.record_cassettes:
        return RecordingModel(model, settings.cassette_dir)
    return model


def _groq(settings: AgentSettings) -> GroqModel:
    if not settings.groq_api_key:
        raise ConfigError("LLM_BACKEND=groq requires GROQ_API_KEY")
    return GroqModel(
        settings.groq_api_key,
        model=settings.groq_model,
        timeout=settings.model_timeout,
        max_output_tokens=settings.model_max_output_tokens,
        ssl_trust=settings.ssl_trust,
    )


def _gemini(settings: AgentSettings) -> GeminiModel:
    if not settings.gemini_api_key:
        raise ConfigError("LLM_BACKEND=gemini requires GEMINI_API_KEY")
    return GeminiModel(
        settings.gemini_api_key,
        model=settings.gemini_model,
        timeout=settings.model_timeout,
        max_output_tokens=settings.model_max_output_tokens,
        ssl_trust=settings.ssl_trust,
    )


__all__ = [
    "CassetteMissError",
    "ChatModel",
    "FallbackModel",
    "GeminiModel",
    "GroqModel",
    "Message",
    "ModelOutputError",
    "ModelProviderError",
    "ModelResponse",
    "RecordingModel",
    "ReplayModel",
    "StubModel",
    "ToolSpec",
    "cassette_key",
    "make_chat_model",
]

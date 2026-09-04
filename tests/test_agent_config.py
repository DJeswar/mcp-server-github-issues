"""Agent settings resolution."""

from __future__ import annotations

import pytest

from agent.config import ALLOWED_TOOLS, load_agent_settings
from server.errors import ConfigError


class TestDefaults:
    def test_stub_backend_and_budgets(self):
        s = load_agent_settings({})
        assert s.llm_backend == "stub"
        assert (s.max_steps, s.max_tool_calls, s.no_progress_limit) == (8, 12, 2)
        assert s.max_wall_clock == 60.0
        assert s.record_cassettes is False

    def test_recursion_limit_sits_above_the_step_budget(self):
        """If LangGraph aborts first, 'answer with what you have' never runs."""
        s = load_agent_settings({"AGENT_MAX_STEPS": "8"})
        assert s.recursion_limit > 2 * s.max_steps

    def test_allowlist_matches_the_server_tools(self):
        assert set(ALLOWED_TOOLS) == {
            "list_issues",
            "get_issue",
            "search_issues",
            "list_labels",
            "list_milestones",
        }


class TestBackendValidation:
    def test_unknown_backend_rejected(self):
        with pytest.raises(ConfigError, match="LLM_BACKEND"):
            load_agent_settings({"LLM_BACKEND": "gpt5"})

    def test_groq_requires_its_key(self):
        with pytest.raises(ConfigError, match="requires GROQ_API_KEY"):
            load_agent_settings({"LLM_BACKEND": "groq"})

    def test_gemini_requires_its_key(self):
        with pytest.raises(ConfigError, match="requires GEMINI_API_KEY"):
            load_agent_settings({"LLM_BACKEND": "gemini"})

    def test_backend_is_case_insensitive(self):
        assert load_agent_settings({"LLM_BACKEND": "STUB"}).llm_backend == "stub"

    def test_auto_requires_at_least_one_key(self):
        with pytest.raises(ConfigError, match="at least one|GROQ_API_KEY"):
            load_agent_settings({"LLM_BACKEND": "auto"})

    def test_auto_accepts_either_key(self):
        assert load_agent_settings(
            {"LLM_BACKEND": "auto", "GEMINI_API_KEY": "g"}
        ).llm_backend == "auto"

    def test_secrets_are_not_in_repr(self):
        settings = load_agent_settings(
            {"LLM_BACKEND": "groq", "GROQ_API_KEY": "top-secret-key"}
        )
        assert "top-secret-key" not in repr(settings)

    def test_live_model_defaults_and_overrides(self):
        default = load_agent_settings({})
        assert default.groq_model == "openai/gpt-oss-20b"
        assert default.gemini_model == "gemini-2.5-flash"
        assert default.model_timeout == 30.0
        assert default.model_max_output_tokens == 4096

        overridden = load_agent_settings(
            {
                "GROQ_MODEL": " custom-groq ",
                "GEMINI_MODEL": " custom-gemini ",
                "MODEL_TIMEOUT_SECONDS": "12.5",
                "MODEL_MAX_OUTPUT_TOKENS": "512",
            }
        )
        assert overridden.groq_model == "custom-groq"
        assert overridden.gemini_model == "custom-gemini"
        assert overridden.model_timeout == 12.5
        assert overridden.model_max_output_tokens == 512

    def test_blank_model_names_use_safe_defaults(self):
        settings = load_agent_settings({"GROQ_MODEL": " ", "GEMINI_MODEL": " "})
        assert settings.groq_model == "openai/gpt-oss-20b"
        assert settings.gemini_model == "gemini-2.5-flash"

    def test_ssl_trust_is_validated(self):
        assert load_agent_settings({"SSL_TRUST_STORE": "SYSTEM"}).ssl_trust == "system"
        with pytest.raises(ConfigError, match="SSL_TRUST_STORE"):
            load_agent_settings({"SSL_TRUST_STORE": "unsafe"})


class TestBudgetValidation:
    def test_non_integer_rejected_by_name(self):
        with pytest.raises(ConfigError, match="AGENT_MAX_STEPS"):
            load_agent_settings({"AGENT_MAX_STEPS": "lots"})

    def test_zero_rejected(self):
        with pytest.raises(ConfigError, match=">= 1"):
            load_agent_settings({"AGENT_MAX_STEPS": "0"})

    def test_blank_falls_back_to_default(self):
        assert load_agent_settings({"AGENT_MAX_STEPS": "  "}).max_steps == 8

    def test_wall_clock_must_be_a_number(self):
        with pytest.raises(ConfigError, match="AGENT_MAX_WALL_CLOCK"):
            load_agent_settings({"AGENT_MAX_WALL_CLOCK": "soon"})

    def test_wall_clock_must_be_positive(self):
        with pytest.raises(ConfigError, match="must be > 0"):
            load_agent_settings({"AGENT_MAX_WALL_CLOCK": "0"})


class TestCassetteSettings:
    def test_record_flag_truthiness(self):
        assert load_agent_settings({"RECORD_CASSETTES": "1"}).record_cassettes is True
        assert load_agent_settings({"RECORD_CASSETTES": "0"}).record_cassettes is False
        assert load_agent_settings({"RECORD_CASSETTES": "false"}).record_cassettes is False

    def test_default_cassette_dir_is_inside_evals(self):
        assert load_agent_settings({}).cassette_dir.name == "cassettes"

    def test_cassette_dir_override(self, tmp_dir):
        s = load_agent_settings({"CASSETTE_DIR": str(tmp_dir)})
        assert s.cassette_dir == tmp_dir


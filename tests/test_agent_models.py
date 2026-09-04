"""ChatModel seam: JSON contract parsing, the stub's determinism, cassette record/replay."""

from __future__ import annotations

import json

import pytest

from agent.config import load_agent_settings
from agent.models import make_chat_model
from agent.models.base import Message, ModelOutputError, ModelResponse, parse_json_object
from agent.models.replay import (
    CassetteMissError,
    RecordingModel,
    ReplayModel,
    cassette_key,
)
from agent.models.stub import StubModel
from agent.prompts import build_plan_messages, build_synthesis_messages
from agent.state import AgentState, Observation
from agent.models.live import GeminiModel, GroqModel


class TestParseJsonObject:
    def test_plain_object(self):
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_unlabelled_fence(self):
        assert parse_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_surrounding_prose(self):
        """Models like to explain themselves before the JSON."""
        assert parse_json_object('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_no_object_raises(self):
        with pytest.raises(ModelOutputError, match="no JSON object"):
            parse_json_object("I would rather not.")

    def test_array_is_rejected(self):
        with pytest.raises(ModelOutputError, match="expected a JSON object"):
            parse_json_object("[1, 2, 3]")

    def test_malformed_object_raises(self):
        with pytest.raises(ModelOutputError):
            parse_json_object('{"a": }')


class TestStubPlanning:
    async def plan_for(self, question: str, observations: list[Observation] | None = None):
        state = AgentState(question=question, observations=observations or [])
        messages = build_plan_messages(state, [])
        response = await StubModel().complete(messages)
        return json.loads(response.text)

    async def test_blocking_release_asks_for_milestones_first(self):
        plan = await self.plan_for("what is blocking the next release?")
        assert plan["action"] == "call_tool"
        assert plan["tool"] == "list_milestones"
        assert plan["why"]

    async def test_second_step_derives_the_milestone_from_the_observation(self):
        """The stub must consume the prior result, not hardcode 'v2'.

        Otherwise the multi-step test would pass even if the loop never fed observations back.
        """
        obs = Observation(
            step=0,
            tool="list_milestones",
            ok=True,
            envelope={"items": [{"title": "v9-custom", "state": "open"}]},
        )
        plan = await self.plan_for("what is blocking the next release?", [obs])
        assert plan["tool"] == "list_issues"
        assert plan["args"]["milestone"] == "v9-custom"
        assert plan["args"]["labels"] == ["blocked"]

    async def test_no_open_milestone_finishes_instead_of_guessing(self):
        obs = Observation(step=0, tool="list_milestones", ok=True, envelope={"items": []})
        plan = await self.plan_for("what is blocking the next release?", [obs])
        assert plan["action"] == "finish"

    async def test_single_issue_question_fetches_that_issue(self):
        plan = await self.plan_for("what does issue #7 say?")
        assert plan["tool"] == "get_issue"
        assert plan["args"]["number"] == 7

    async def test_label_question_lists_labels(self):
        plan = await self.plan_for("which labels exist in this repo?")
        assert plan["tool"] == "list_labels"

    async def test_fallback_lists_open_issues(self):
        plan = await self.plan_for("give me a general overview please")
        assert plan["tool"] == "list_issues"
        assert plan["args"]["state"] == "open"

    async def test_finishes_once_observations_exist(self):
        obs = Observation(step=0, tool="list_issues", ok=True, envelope={"items": []})
        plan = await self.plan_for("general overview", [obs])
        assert plan["action"] == "finish"


class TestStubDeterminism:
    async def test_same_prompt_gives_byte_identical_output(self):
        state = AgentState(question="what is blocking the next release?")
        messages = build_plan_messages(state, [])
        model = StubModel()
        first = await model.complete(messages)
        second = await model.complete(messages)
        assert first.text == second.text

    async def test_synthesis_is_deterministic(self):
        state = AgentState(
            question="anything",
            observations=[
                Observation(
                    step=0,
                    tool="list_issues",
                    ok=True,
                    envelope={
                        "repo": "o/r",
                        "backend": "fixture",
                        "fetched_at": "2026-08-01T00:00:00Z",
                        "items": [
                            {
                                "number": 1,
                                "title": "T",
                                "assignees": ["a"],
                                "days_since_update": 9.0,
                            }
                        ],
                        "notes": [],
                    },
                )
            ],
        )
        messages = build_synthesis_messages(state)
        model = StubModel()
        assert (await model.complete(messages)).text == (await model.complete(messages)).text


class TestCassettes:
    def test_key_is_stable_across_calls(self):
        messages = [Message(role="user", content="hello")]
        assert cassette_key(messages, None) == cassette_key(messages, None)

    def test_key_changes_with_content(self):
        a = cassette_key([Message(role="user", content="a")], None)
        b = cassette_key([Message(role="user", content="b")], None)
        assert a != b

    async def test_record_then_replay_round_trip(self, tmp_dir):
        messages = [Message(role="user", content="<question>hi</question>")]
        recorder = RecordingModel(StubModel(), tmp_dir)
        recorded = await recorder.complete(messages)

        written = list(tmp_dir.glob("*.json"))
        assert len(written) == 1

        replayed = await ReplayModel(tmp_dir).complete(messages)
        assert replayed.text == recorded.text

    async def test_cassette_file_records_the_request_too(self, tmp_dir):
        messages = [Message(role="user", content="<question>hi</question>")]
        await RecordingModel(StubModel(), tmp_dir).complete(messages)
        data = json.loads(next(tmp_dir.glob("*.json")).read_text(encoding="utf-8"))
        assert data["request"]["messages"][0]["content"] == "<question>hi</question>"
        assert "response" in data and "key" in data

    async def test_miss_explains_how_to_record(self, tmp_dir):
        with pytest.raises(CassetteMissError, match="RECORD_CASSETTES=1"):
            await ReplayModel(tmp_dir).complete([Message(role="user", content="nope")])


class TestFactory:
    def test_stub_is_the_default(self):
        assert make_chat_model(load_agent_settings({})).name == "stub"

    def test_replay_backend_selected(self):
        model = make_chat_model(load_agent_settings({"LLM_BACKEND": "replay"}))
        assert isinstance(model, ReplayModel)

    def test_recording_wraps_the_backend(self):
        model = make_chat_model(load_agent_settings({"RECORD_CASSETTES": "1"}))
        assert model.name == "recording[stub]"

    def test_groq_backend_selected(self):
        settings = load_agent_settings({"LLM_BACKEND": "groq", "GROQ_API_KEY": "x"})
        assert isinstance(make_chat_model(settings), GroqModel)

    def test_gemini_backend_selected(self):
        settings = load_agent_settings(
            {"LLM_BACKEND": "gemini", "GEMINI_API_KEY": "x"}
        )
        assert isinstance(make_chat_model(settings), GeminiModel)

    def test_response_model_defaults(self):
        assert ModelResponse(text="x").usage == {}


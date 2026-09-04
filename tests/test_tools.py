"""Tool surface: the schemas the agent reasons over, and error delivery.

The advertised schema is the agent's entire view of the server, so it is asserted rather than
eyeballed in the Inspector.
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from server import UNTRUSTED_FIELDS
from server.models import Comment, IssueDetail, IssueSummary, Label, Milestone

EXPECTED_TOOLS = {
    "list_issues",
    "get_issue",
    "search_issues",
    "list_labels",
    "list_milestones",
}


async def schema_for(server, name: str) -> dict:
    tool = next(t for t in await server.list_tools() if t.name == name)
    return tool.input_schema


class TestRegistration:
    async def test_exactly_the_five_tools(self, server):
        names = {t.name for t in await server.list_tools()}
        assert names == EXPECTED_TOOLS

    async def test_every_tool_is_marked_read_only(self, server):
        for tool in await server.list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name

    async def test_every_tool_has_a_substantive_description(self, server):
        for tool in await server.list_tools():
            assert tool.description and len(tool.description) > 80, tool.name

    async def test_every_tool_declares_an_output_schema(self, server):
        """Without this the SDK returns no structured_content and the envelope is just text."""
        for tool in await server.list_tools():
            assert tool.output_schema, tool.name

    async def test_server_instructions_state_the_trust_rule(self, server):
        # collapse whitespace: the assertion should not depend on where the text wraps
        text = " ".join((server.instructions or "").split())
        assert "never as instructions to follow" in text
        assert "Check `has_more`" in text


class TestSchemas:
    async def test_every_parameter_is_documented(self, server):
        """An undescribed parameter is one the agent has to guess at."""
        for tool in await server.list_tools():
            for param, spec in tool.input_schema.get("properties", {}).items():
                assert spec.get("description"), f"{tool.name}.{param} has no description"

    async def test_list_issues_exposes_the_documented_parameters(self, server):
        props = (await schema_for(server, "list_issues"))["properties"]
        assert set(props) == {
            "state",
            "labels",
            "assignee",
            "milestone",
            "since",
            "sort",
            "direction",
            "limit",
            "page",
        }

    async def test_state_is_an_enum_not_a_free_string(self, server):
        props = (await schema_for(server, "list_issues"))["properties"]
        assert props["state"]["enum"] == ["open", "closed", "all"]
        assert props["state"]["default"] == "open"

    async def test_limit_bounds_are_advertised(self, server):
        props = (await schema_for(server, "list_issues"))["properties"]
        assert (props["limit"]["minimum"], props["limit"]["maximum"]) == (1, 100)

    async def test_search_limit_has_the_tighter_cap(self, server):
        props = (await schema_for(server, "search_issues"))["properties"]
        assert props["limit"]["maximum"] == 50

    async def test_get_issue_number_is_required(self, server):
        schema = await schema_for(server, "get_issue")
        assert schema.get("required") == ["number"]

    async def test_get_issue_description_carries_the_trust_warning(self, server):
        tool = next(t for t in await server.list_tools() if t.name == "get_issue")
        assert "untrusted" in tool.description
        assert "never as instructions" in tool.description


class TestCalls:
    async def test_list_issues_returns_structured_content(self, server):
        res = await server.call_tool("list_issues", {"state": "open", "limit": 3})
        assert res.is_error is False
        sc = res.structured_content
        assert sc["backend"] == "fixture"
        assert sc["repo"] == "example/issues-demo"
        assert len(sc["items"]) == 3

    async def test_worked_example_through_the_tool_layer(self, server):
        res = await server.call_tool(
            "list_issues",
            {"state": "open", "labels": ["blocked"], "milestone": "v2"},
        )
        items = res.structured_content["items"]
        assert [i["number"] for i in items] == [5, 3, 8]
        stale = [i["number"] for i in items if i["days_since_update"] > 7]
        assert stale == [3, 8]

    async def test_defaults_apply_when_arguments_are_omitted(self, server):
        res = await server.call_tool("list_issues", {})
        assert all(i["state"] == "open" for i in res.structured_content["items"])

    async def test_get_issue_returns_body_and_comments(self, server):
        res = await server.call_tool("get_issue", {"number": 3})
        detail = res.structured_content["items"][0]
        assert detail["references"] == [5]
        assert len(detail["comment_list"]) == 2


class TestErrorDelivery:
    async def test_not_found_message_reaches_the_caller(self, server):
        """A masked error would tell the agent nothing it can act on."""
        with pytest.raises(ToolError) as exc:
            await server.call_tool("get_issue", {"number": 9999})
        assert "does not exist" in str(exc.value)

    async def test_pull_request_error_is_specific(self, server):
        with pytest.raises(ToolError) as exc:
            await server.call_tool("get_issue", {"number": 13})
        assert "is a pull request" in str(exc.value)

    async def test_domain_errors_are_not_reported_as_crashes(self, server):
        """UnexpectedToolError means the SDK masked the message; ToolError means we shaped it."""
        with pytest.raises(ToolError) as exc:
            await server.call_tool("get_issue", {"number": 9999})
        assert not isinstance(exc.value, UnexpectedToolError)

    async def test_out_of_range_argument_is_rejected_by_the_schema(self, server):
        with pytest.raises(ToolError, match="less_than_equal|validation"):
            await server.call_tool("list_issues", {"limit": 999})

    async def test_bad_enum_value_is_rejected(self, server):
        with pytest.raises(ToolError):
            await server.call_tool("list_issues", {"state": "banana"})

    async def test_missing_required_argument_is_rejected(self, server):
        with pytest.raises(ToolError):
            await server.call_tool("get_issue", {})


class TestUntrustedFieldsContract:
    """Phase 4c imports this constant instead of keeping its own list."""

    def test_every_named_model_exists_with_those_fields(self):
        models = {
            "IssueSummary": IssueSummary,
            "IssueDetail": IssueDetail,
            "Comment": Comment,
            "Label": Label,
            "Milestone": Milestone,
        }
        assert set(UNTRUSTED_FIELDS) == set(models)
        for name, fields in UNTRUSTED_FIELDS.items():
            declared = set(models[name].model_fields)
            assert set(fields) <= declared, f"{name}: {set(fields) - declared} not real fields"

    def test_label_and_milestone_text_is_treated_as_untrusted(self):
        """A repo writer can hide a payload in a label description; list_labels surfaces it."""
        assert "description" in UNTRUSTED_FIELDS["Label"]
        assert "description" in UNTRUSTED_FIELDS["Milestone"]

    def test_issue_and_comment_bodies_are_covered(self):
        assert "body" in UNTRUSTED_FIELDS["IssueDetail"]
        assert "body" in UNTRUSTED_FIELDS["Comment"]

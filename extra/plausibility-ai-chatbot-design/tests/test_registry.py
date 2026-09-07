"""Tool Registry: allowlist behavior, duplicate rejection, audit dispatch."""

import pytest

from tool_registry import ToolRegistry, UnknownToolError
from tools import ListScenariosTool
from tools.base import ToolResult


class FakeScenarioAPI:
    async def list_scenarios(self, obo_token):
        return []

    async def get_scenario(self, scenario_id, obo_token):
        return {}


def make_tool():
    return ListScenariosTool(FakeScenarioAPI())


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        ToolRegistry([make_tool(), make_tool()])


def test_unregistered_tool_is_unreachable():
    registry = ToolRegistry([make_tool()])
    assert "list_scenarios" in registry
    assert "search_the_web" not in registry
    with pytest.raises(UnknownToolError):
        registry.get("search_the_web")


def test_openai_tools_payload_lists_registered_tools():
    registry = ToolRegistry([make_tool()])
    payload = registry.openai_tools()
    assert [t["function"]["name"] for t in payload] == ["list_scenarios"]


async def test_dispatch_unknown_name_returns_error_not_raise(context):
    registry = ToolRegistry([make_tool()])
    result = await registry.dispatch("nope", "{}", context)
    assert result.status == "error"


async def test_dispatch_invalid_json_args_still_calls_tool(context):
    registry = ToolRegistry([make_tool()])
    result = await registry.dispatch("list_scenarios", "{not json", context)
    assert result.status == "ok"  # list_scenarios takes no args

"""`list_scenarios` tool — live scenario list from the internal scenario API."""

from __future__ import annotations

from typing import Any, Mapping

from tools.base import Tool, ToolContext, ToolResult, validate_args
from tools.scenario_api import ScenarioAPI, ScenarioAPIError


class ListScenariosTool(Tool):
    name = "list_scenarios"
    version = "1.0.0"
    description = (
        "List the available economist-authored scenarios (versioned forecast "
        "runs with fixed inputs and precomputed outputs). Use this to resolve "
        "scenario names to IDs before comparing."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, scenario_api: ScenarioAPI) -> None:
        self._scenario_api = scenario_api

    async def call(self, args: Mapping[str, Any], context: ToolContext) -> ToolResult:
        if error := validate_args(self.args_schema, args):
            return ToolResult.failure(error)
        try:
            scenarios = await self._scenario_api.list_scenarios(context.obo_token)
        except ScenarioAPIError as exc:
            return ToolResult.failure(str(exc))
        except Exception:
            return ToolResult.failure("scenario API unavailable")
        return ToolResult.ok({"scenarios": list(scenarios)})

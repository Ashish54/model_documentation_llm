"""`get_scenario_data` tool — full precomputed outputs for one scenario."""

from __future__ import annotations

from typing import Any, Mapping

from tools.base import Tool, ToolContext, ToolResult, validate_args
from tools.scenario_api import ScenarioAPI, ScenarioAPIError


class GetScenarioDataTool(Tool):
    name = "get_scenario_data"
    version = "1.0.0"
    description = (
        "Fetch the fixed inputs and precomputed outputs of one scenario by ID. "
        "Scenario numbers always come from this API — never estimate them."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "scenario_id": {
                "type": "string",
                "description": "Scenario identifier, e.g. from list_scenarios.",
            },
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    }

    def __init__(self, scenario_api: ScenarioAPI) -> None:
        self._scenario_api = scenario_api

    async def call(self, args: Mapping[str, Any], context: ToolContext) -> ToolResult:
        if error := validate_args(self.args_schema, args):
            return ToolResult.failure(error)
        try:
            scenario = await self._scenario_api.get_scenario(
                args["scenario_id"], context.obo_token
            )
        except ScenarioAPIError as exc:
            return ToolResult.failure(str(exc))
        except Exception:
            return ToolResult.failure("scenario API unavailable")
        return ToolResult.ok({"scenario": scenario})

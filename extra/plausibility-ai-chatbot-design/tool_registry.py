"""Tool Registry — the orchestrator's allowlisted extension point (§3.6).

Static in-code registry built at startup: registering a tool is a reviewed,
deliberate step, not open plugin loading. The orchestrator dispatches model
`tool_calls` exclusively through this registry, so anything not registered is
unreachable by the LLM.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Iterable, Mapping, Optional

from tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class UnknownToolError(KeyError):
    pass


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("tool must declare a name")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool registration: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def openai_tools(self) -> list[dict]:
        """`tools=` payload for the chat completion call."""
        return [tool.openai_schema() for tool in self._tools.values()]

    async def dispatch(
        self,
        name: str,
        arguments_json: str,
        context: ToolContext,
        *,
        model_id: Optional[str] = None,
    ) -> ToolResult:
        """Validate + invoke one model-requested tool call, with audit logging
        (tool name+version, model id, latency, per-user attribution — §5)."""
        started = time.monotonic()
        try:
            tool = self.get(name)
        except UnknownToolError:
            logger.warning(
                "tool_call_rejected tool=%s user=%s correlation_id=%s reason=not_registered",
                name, context.user_id, context.correlation_id,
            )
            return ToolResult.failure(f"tool not available: {name}")

        try:
            args: Mapping = json.loads(arguments_json or "{}")
        except json.JSONDecodeError:
            args = {}

        result = await tool.call(args, context)
        logger.info(
            "tool_call tool=%s version=%s model=%s user=%s correlation_id=%s "
            "status=%s latency_ms=%.1f",
            tool.name, tool.version, model_id, context.user_id,
            context.correlation_id, result.status,
            (time.monotonic() - started) * 1000,
        )
        return result

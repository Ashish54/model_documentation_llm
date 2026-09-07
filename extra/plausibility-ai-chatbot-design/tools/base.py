"""Tool contract for the orchestrator's Tool Registry (ARCHITECTURE §3.6).

Every tool exposes ``name``, ``version``, ``description``, a JSON Schema for
its arguments, and an async ``call(args, context) -> ToolResult``. Results are
structured payloads — the LLM narrates structured data, never raw prose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ToolContext:
    """Per-request context handed to every tool call.

    Carries the authenticated user's identity/claims (used for OBO calls to
    scenario APIs and for the pgvector ACL security filter) and a correlation
    ID for audit logging. Per-user attribution for AIaaS calls is done in
    orchestrator-side logging keyed off this context.
    """

    user_id: str
    group_claims: frozenset[str]
    correlation_id: str
    obo_token: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    """Structured tool result per the §3.6 contract."""

    status: str  # "ok" | "error"
    data: Any = None
    error: Optional[str] = None

    @classmethod
    def ok(cls, data: Any) -> "ToolResult":
        return cls(status="ok", data=data)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(status="error", error=error)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "data": self.data, "error": self.error}


class Tool(ABC):
    """Common interface for every registered (allowlisted) tool."""

    name: str
    version: str
    description: str
    args_schema: Mapping[str, Any]  # JSON Schema for the arguments object

    @abstractmethod
    async def call(
        self, args: Mapping[str, Any], context: ToolContext
    ) -> ToolResult:
        """Execute the tool. Must not raise for upstream failures — return
        ToolResult.failure instead so the orchestrator loop degrades
        gracefully and the LLM can narrate a 'tool unavailable' outcome."""

    def openai_schema(self) -> dict[str, Any]:
        """OpenAI-compatible `tools=` entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.args_schema),
            },
        }


def validate_args(
    schema: Mapping[str, Any], args: Mapping[str, Any]
) -> Optional[str]:
    """Minimal JSON Schema validation (required + declared properties + type).

    Returns an error string, or None when valid. Kept dependency-free; the
    schemas we declare are deliberately small.
    """
    if schema.get("type") != "object":
        return None
    required: Sequence[str] = schema.get("required", [])
    properties: Mapping[str, Any] = schema.get("properties", {})
    for key in required:
        if key not in args:
            return f"missing required argument: {key}"
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": Mapping,
    }
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            if schema.get("additionalProperties", True) is False:
                return f"unexpected argument: {key}"
            continue
        expected = spec.get("type")
        py_type = type_map.get(expected)
        if py_type is not None and not isinstance(value, py_type):
            return f"argument {key!r} must be of type {expected}"
        # bool is a subclass of int — reject bools for integer/number.
        if expected in ("integer", "number") and isinstance(value, bool):
            return f"argument {key!r} must be of type {expected}"
    return None

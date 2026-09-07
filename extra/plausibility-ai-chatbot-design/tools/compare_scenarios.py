"""`compare_scenarios` tool — thin wrapper around the EXISTING economist/data
team comparison Python package. No comparison logic lives here (plan Step 2).

The wrapped callable takes two scenario IDs and returns a structured result
(numbers + labeled fields, not prose). Metrics are applied as a filter on the
output, never on the inputs (CONTEXT.md).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Optional, Sequence

from tools.base import Tool, ToolContext, ToolResult, validate_args

# Signature of the existing comparison workflow, once imported.
CompareFn = Callable[[str, str], Mapping[str, Any]]


def load_comparison_workflow() -> CompareFn:
    """Import the economist/data-team comparison package (lazily, so tests and
    dev environments without the internal package still work)."""
    from scenario_comparison import compare  # type: ignore[import-not-found]

    return compare


class CompareScenariosTool(Tool):
    name = "compare_scenarios"
    version = "1.0.0"
    description = (
        "Compare two whole scenarios using the deterministic, versioned "
        "comparison workflow owned by the economist/data team. Returns "
        "structured deltas/metrics (ground truth to narrate — never recompute "
        "them yourself). `metrics` filters which metrics appear in the "
        "output; it never changes the inputs to the comparison."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "scenario_a": {"type": "string", "description": "First scenario ID."},
            "scenario_b": {"type": "string", "description": "Second scenario ID."},
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional output filter: metric names to include.",
            },
        },
        "required": ["scenario_a", "scenario_b"],
        "additionalProperties": False,
    }

    def __init__(self, compare_fn: Optional[CompareFn] = None) -> None:
        self._compare_fn = compare_fn

    def _resolve_fn(self) -> CompareFn:
        return self._compare_fn if self._compare_fn is not None else load_comparison_workflow()

    async def call(self, args: Mapping[str, Any], context: ToolContext) -> ToolResult:
        if error := validate_args(self.args_schema, args):
            return ToolResult.failure(error)
        if args["scenario_a"] == args["scenario_b"]:
            return ToolResult.failure("scenario_a and scenario_b must differ")
        try:
            compare_fn = self._resolve_fn()
            result = await asyncio.to_thread(
                compare_fn, args["scenario_a"], args["scenario_b"]
            )
        except ImportError:
            return ToolResult.failure("comparison workflow package unavailable")
        except Exception as exc:
            return ToolResult.failure(f"comparison workflow failed: {exc}")

        data: dict[str, Any] = dict(result)
        metrics_filter: Optional[Sequence[str]] = args.get("metrics")
        if metrics_filter and isinstance(data.get("metrics"), Mapping):
            wanted = set(metrics_filter)
            data["metrics"] = {
                k: v for k, v in data["metrics"].items() if k in wanted
            }
        return ToolResult.ok(data)

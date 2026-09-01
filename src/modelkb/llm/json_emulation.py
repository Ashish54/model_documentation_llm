"""JSON extraction from chat-only model output (no native tool/JSON support).

Ported from the standalone vLLM proxy (tools/vllm_proxy.py) that this package
supersedes. Tolerant of markdown fences and surrounding prose, strict about
the final parse.
"""

from __future__ import annotations

import json
from typing import Any


def build_json_instruction(schema: dict[str, Any], *, requirement: str) -> str:
    return (
        f"{requirement}\n\n"
        "Respond with ONLY a single JSON object matching this JSON schema. "
        "Do not wrap it in markdown fences. Do not add any prose before or after.\n\n"
        f"JSON schema:\n{json.dumps(schema, indent=2)}"
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort extraction of one JSON object from model output."""
    candidate = text.strip()

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Scan for the first balanced {...} block (string-aware).
    start = candidate.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(candidate[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(result, dict):
                        return result
                    break
        start = candidate.find("{", start + 1)

    raise ValueError(f"model did not return a JSON object: {text[:200]!r}")

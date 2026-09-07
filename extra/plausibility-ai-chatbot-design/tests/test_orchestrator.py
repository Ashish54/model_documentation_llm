"""Orchestrator core-loop tests: full tool-calling round trip with a scripted
fake LLM (plan Verification 2 shape, without the live gateway), in-memory
session behavior (ADR-0003), and guardrail/registry enforcement."""

import json

from llm_client import ChatResponse
from orchestrator import Orchestrator, SYSTEM_PROMPT
from tool_registry import ToolRegistry
from tools import ListScenariosTool
from tools.base import Tool, ToolResult


class ScriptedLLM:
    """Fake chat model that replays queued responses and records requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def chat(self, messages, *, model, tools=None, **kwargs):
        self.requests.append({"messages": list(messages), "model": model, "tools": tools})
        if not self._responses:
            raise AssertionError("ScriptedLLM ran out of responses")
        return self._responses.pop(0)


def completion(content=None, tool_calls=(), usage=(10, 5)):
    raw_tool_calls = [
        {
            "id": tc[0],
            "type": "function",
            "function": {"name": tc[1], "arguments": tc[2]},
        }
        for tc in tool_calls
    ]
    return ChatResponse.from_api(
        {
            "model": "Qwen/Qwen3.6-27B",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content,
                                "tool_calls": raw_tool_calls or None},
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                      "total_tokens": sum(usage)},
        }
    )


class FakeScenarioAPI:
    async def list_scenarios(self, obo_token):
        return [{"id": "scn-a", "name": "Baseline FY26"}]

    async def get_scenario(self, scenario_id, obo_token):
        return {"id": scenario_id}


def make_orchestrator(llm, **kwargs):
    registry = ToolRegistry([ListScenariosTool(FakeScenarioAPI())])
    return Orchestrator(
        llm, registry, chat_model="Qwen/Qwen3.6-27B", **kwargs
    )


async def test_full_tool_calling_round_trip(context):
    """Model requests list_scenarios → tool result appended → final answer."""
    llm = ScriptedLLM(
        [
            completion(tool_calls=[("call_1", "list_scenarios", "{}")]),
            completion(content="There is one scenario: Baseline FY26 (scn-a)."),
        ]
    )
    orch = make_orchestrator(llm)
    session = orch.new_session()

    answer = await orch.handle_message(session, "What scenarios exist?", context)

    assert answer == "There is one scenario: Baseline FY26 (scn-a)."
    # Second model call must include the tool result message.
    second_call_messages = llm.requests[1]["messages"]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    payload = json.loads(tool_messages[0]["content"])
    assert payload["status"] == "ok"
    assert payload["data"]["scenarios"][0]["id"] == "scn-a"
    # Tools were offered via the native tools= parameter.
    assert llm.requests[0]["tools"][0]["function"]["name"] == "list_scenarios"


async def test_system_prompt_scopes_every_session(context):
    llm = ScriptedLLM([completion(content="ok")])
    orch = make_orchestrator(llm)
    session = orch.new_session()
    await orch.handle_message(session, "hi", context)
    first = llm.requests[0]["messages"][0]
    assert first["role"] == "system"
    assert "ONLY" in first["content"]  # scoping guardrail present


async def test_history_persists_within_session_in_memory(context):
    llm = ScriptedLLM([completion(content="first"), completion(content="second")])
    orch = make_orchestrator(llm)
    session = orch.new_session()
    await orch.handle_message(session, "q1", context)
    await orch.handle_message(session, "q2", context)
    second_call_messages = llm.requests[1]["messages"]
    user_messages = [m["content"] for m in second_call_messages if m["role"] == "user"]
    assert user_messages == ["q1", "q2"]


async def test_sessions_are_isolated(context):
    llm = ScriptedLLM([completion(content="a"), completion(content="b")])
    orch = make_orchestrator(llm)
    s1, s2 = orch.new_session(), orch.new_session()
    await orch.handle_message(s1, "only in s1", context)
    await orch.handle_message(s2, "only in s2", context)
    contents_s2 = [m.get("content") for m in orch.get_history(s2)]
    assert "only in s1" not in contents_s2


async def test_unknown_tool_call_returns_structured_error_to_model(context):
    """The registry is an allowlist: unregistered tools are unreachable."""
    llm = ScriptedLLM(
        [
            completion(tool_calls=[("call_9", "delete_everything", "{}")]),
            completion(content="I can't do that."),
        ]
    )
    orch = make_orchestrator(llm)
    answer = await orch.handle_message(orch.new_session(), "delete everything", context)
    assert answer == "I can't do that."
    tool_msg = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"][0]
    assert json.loads(tool_msg["content"])["status"] == "error"


async def test_tool_loop_bounded_by_max_rounds(context):
    llm = ScriptedLLM(
        [completion(tool_calls=[("c", "list_scenarios", "{}")]) for _ in range(10)]
    )
    orch = make_orchestrator(llm, max_tool_rounds=2)
    answer = await orch.handle_message(orch.new_session(), "loop", context)
    assert "wasn't able to complete" in answer
    assert len(llm.requests) == 3  # initial + 2 rounds


class SlowTool(Tool):
    name = "slow_tool"
    version = "1.0.0"
    description = "hangs forever"
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def call(self, args, context):
        import asyncio

        await asyncio.sleep(60)
        return ToolResult.ok({})


async def test_slow_tool_degrades_gracefully(context):
    """A hanging tool yields a narratable 'tool unavailable' result, not a crash."""
    import asyncio

    llm = ScriptedLLM(
        [
            completion(tool_calls=[("c1", "slow_tool", "{}")]),
            completion(content="The tool is unavailable right now."),
        ]
    )
    registry = ToolRegistry([SlowTool()])
    orch = Orchestrator(
        llm, registry, chat_model="Qwen/Qwen3.6-27B", tool_call_timeout_s=0.05
    )
    answer = await orch.handle_message(orch.new_session(), "use the slow tool", context)
    assert answer == "The tool is unavailable right now."
    tool_msg = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "unavailable" in json.loads(tool_msg["content"])["error"]

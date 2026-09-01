"""Provider tests with a mocked vLLM transport (no server needed).

Covers required-test #6 at the provider level: invalid LLM structured output
is rejected and every failure is recorded.
"""

import httpx
import pytest
from pydantic import BaseModel

from modelkb.core.config import VllmSettings
from modelkb.llm.base import InteractionRecord, LlmCall, LlmValidationError
from modelkb.llm.provider import VllmProvider


class Widget(BaseModel):
    name: str
    count: int


def _openai_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def _provider(
    responses: list[httpx.Response], records: list[InteractionRecord], backend: str = "chat_only"
) -> VllmProvider:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        handler.requests.append(request)
        return queue.pop(0) if queue else _openai_response('{"name": "x", "count": 1}')

    handler.requests = []  # type: ignore[attr-defined]
    settings = VllmSettings(
        backend=backend, base_url="http://testserver/v1", model="test-model", max_retries=0
    )
    return VllmProvider(
        settings,
        recorder=records.append,
        transport=httpx.MockTransport(handler),
    )


def _call() -> LlmCall:
    return LlmCall(
        purpose="test",
        prompt_version="test_v1",
        messages=[{"role": "user", "content": "make a widget"}],
    )


def test_chat_only_parses_fenced_json() -> None:
    records: list[InteractionRecord] = []
    provider = _provider([_openai_response('```json\n{"name": "a", "count": 2}\n```')], records)
    outcome = provider.complete_structured(_call(), Widget)
    assert outcome.parsed == Widget(name="a", count=2)
    assert outcome.attempts == 1
    assert [r.status for r in records] == ["success"]
    # the emulation appended a JSON-schema instruction
    sent = records[0].request_payload or {}
    assert sent, "request payload was recorded"
    assert sent["messages"][-1]["role"] == "system"


def test_chat_only_repairs_once_then_succeeds() -> None:
    records: list[InteractionRecord] = []
    provider = _provider(
        [
            _openai_response("I cannot do that."),  # not JSON
            _openai_response('{"name": "fixed", "count": 3}'),
        ],
        records,
    )
    outcome = provider.complete_structured(_call(), Widget)
    assert outcome.parsed.count == 3
    assert outcome.attempts == 2
    assert [r.status for r in records] == ["validation_failed", "success"]


def test_invalid_output_twice_raises_and_records() -> None:
    records: list[InteractionRecord] = []
    provider = _provider(
        [_openai_response("nonsense"), _openai_response('{"wrong": "shape"}')], records
    )
    with pytest.raises(LlmValidationError) as excinfo:
        provider.complete_structured(_call(), Widget)
    assert len(excinfo.value.errors) == 2
    assert [r.status for r in records] == ["validation_failed", "validation_failed"]
    assert all(r.validation_errors for r in records)


def test_direct_backend_sends_response_format() -> None:
    records: list[InteractionRecord] = []
    provider = _provider([_openai_response('{"name": "d", "count": 1}')], records, backend="direct")
    outcome = provider.complete_structured(_call(), Widget)
    assert outcome.parsed.name == "d"
    payload = records[0].request_payload
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "Widget"


def test_transport_error_is_recorded() -> None:
    records: list[InteractionRecord] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = VllmSettings(
        backend="chat_only", base_url="http://testserver/v1", model="m", max_retries=0
    )
    provider = VllmProvider(
        settings, recorder=records.append, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LlmValidationError, match="transport"):
        provider.complete_structured(_call(), Widget)
    assert [r.status for r in records] == ["error"]

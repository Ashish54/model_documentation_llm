"""llm_client tests: bounded concurrency, retries/backoff, auth header,
response parsing. Transport is faked via an injected httpx.AsyncClient."""

import asyncio

import httpx
import pytest

from llm_client import (
    ChatResponse,
    LLMClient,
    LLMClientError,
    MAX_CHAT_CONCURRENCY,
    RateLimitError,
)


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://gw.test/v1")
    return LLMClient(
        token_provider=lambda: _token(),
        http_client=http_client,
        backoff_base_s=0.0,
        **kwargs,
    )


async def _token():
    return "broker-token"


def chat_payload(content="hello", tool_calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-1",
        "model": "Qwen/Qwen3.6-27B",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def test_chat_sends_bearer_token_and_parses_response():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(200, json=chat_payload(content="done"))

    client = make_client(handler)
    response = await client.chat([{"role": "user", "content": "hi"}])
    assert seen["auth"] == "Bearer broker-token"
    assert b'"model":"Qwen/Qwen3.6-27B"' in seen["body"]
    assert response.content == "done"
    assert response.usage.total_tokens == 15
    assert response.tool_calls == ()


async def test_chat_parses_tool_calls():
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "list_scenarios", "arguments": "{}"},
        }
    ]
    client = make_client(lambda r: httpx.Response(200, json=chat_payload(None, tool_calls)))
    response = await client.chat([], tools=[{"type": "function"}])
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "list_scenarios"
    assert response.tool_calls[0].id == "call_1"


async def test_retries_on_429_then_succeeds():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json=chat_payload())

    client = make_client(handler, max_retries=3)
    response = await client.chat([])
    assert response.content == "hello"
    assert len(attempts) == 3


async def test_persistent_429_raises_rate_limit_error():
    client = make_client(lambda r: httpx.Response(429), max_retries=2)
    with pytest.raises(RateLimitError):
        await client.chat([])


async def test_persistent_5xx_raises_client_error():
    client = make_client(lambda r: httpx.Response(503), max_retries=2)
    with pytest.raises(LLMClientError):
        await client.chat([])


async def test_4xx_other_than_401_fails_fast_without_retry():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(400, json={"error": "bad request"})

    client = make_client(handler, max_retries=3)
    with pytest.raises(LLMClientError):
        await client.chat([])
    assert len(attempts) == 1


async def test_concurrency_is_bounded():
    in_flight = 0
    max_in_flight = 0

    async def slow_response():
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return httpx.Response(200, json=chat_payload())

    async def async_handler(request):
        return await slow_response()

    transport = httpx.MockTransport(async_handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://gw.test/v1")
    client = LLMClient(
        token_provider=_token,
        http_client=http_client,
        max_concurrency=2,
        backoff_base_s=0.0,
    )
    await asyncio.gather(*[client.chat([]) for _ in range(6)])
    assert max_in_flight <= 2


async def test_concurrency_cannot_exceed_gateway_ceiling():
    with pytest.raises(ValueError):
        make_client(lambda r: httpx.Response(200), max_concurrency=MAX_CHAT_CONCURRENCY + 1)


async def test_embed_preserves_input_order():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "object": "list",
                # Deliberately out of order to prove index-based sorting.
                "data": [
                    {"index": 1, "embedding": [0.2, 0.2]},
                    {"index": 0, "embedding": [0.1, 0.1]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    client = make_client(handler)
    vectors = await client.embed(["first", "second"])
    assert vectors == [[0.1, 0.1], [0.2, 0.2]]


def test_no_tls_verification_disabled_anywhere():
    """Security check (plan Verification 5): no verify=False in any real call.

    Walks the AST of every production module so docstring mentions of the
    anti-pattern don't count, but any actual `verify=False` keyword fails.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.glob("**/*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "verify":
                if isinstance(node.value, ast.Constant) and node.value.value is False:
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []

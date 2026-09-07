"""Internal client for the AIaaS gateway (chat + embeddings).

Wraps DevPod broker authentication (``AzureAuthClient`` / ``AuthMode.DEVPOD``,
auto-refreshing) and an OpenAI-compatible HTTP client pointed at the AIaaS
gateway. Both the chat model (``Qwen/Qwen3.6-27B``) and the embedding model
(``Qwen/Qwen3-Embedding-8B``) are reached through the same gateway endpoint
with the same broker token — they are distinct model IDs, not distinct clients.

Design constraints enforced here (from the AIMart catalog / vllm_specs.md):
  * Bounded concurrency — a semaphore keeps in-flight requests under the
    64-concurrency chat ceiling (and the 15 RPS gateway ceiling).
  * Retries with exponential backoff + jitter on 429 and 5xx responses.
  * Request timeout above the 45s P95 latency SLO.
  * TLS verification is always on; pass an internal CA bundle via
    ``ca_bundle`` when the environment requires it. ``verify=False`` is
    never used.
  * Tokens are never logged.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "Qwen/Qwen3.6-27B"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_GATEWAY_BASE_URL = (
    "https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1"
)
DEFAULT_BROKER_URL = (
    "https://aiaas-broker.uk8s-tsshared-weu-gt021-ext-p001.azpriv-cloud.ubs.net/"
)

# Capacity ceilings from the AIaaS consumption plan (catalog benchmark values;
# confirm against the applicable Consumption Plan before raising them).
MAX_GATEWAY_RPS = 15
MAX_CHAT_CONCURRENCY = 64
P95_LATENCY_SLO_S = 45.0
REQUEST_TIMEOUT_S = 60.0  # headroom above the P95 SLO


class LLMClientError(Exception):
    """Base error for AIaaS gateway failures."""


class RateLimitError(LLMClientError):
    """The gateway kept rejecting requests after all retries."""


class AuthenticationError(LLMClientError):
    """Broker token was rejected and re-authentication did not help."""


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str  # raw JSON string as returned by the model


@dataclass(frozen=True)
class ChatResponse:
    """Parsed view over an OpenAI-compatible chat completion."""

    content: Optional[str]
    tool_calls: tuple[ToolCall, ...]
    finish_reason: Optional[str]
    model: Optional[str]
    usage: TokenUsage
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "ChatResponse":
        choice = payload["choices"][0]
        message = choice.get("message") or {}
        tool_calls = tuple(
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments_json=tc["function"].get("arguments") or "{}",
            )
            for tc in (message.get("tool_calls") or [])
        )
        usage_raw = payload.get("usage") or {}
        return cls(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            model=payload.get("model"),
            usage=TokenUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            ),
            raw=payload,
        )


# A token provider returns a valid bearer token for the gateway. It is
# responsible for caching/refresh (e.g. AzureAuthClient with auto_refresh).
TokenProvider = Callable[[], Awaitable[str]]


def make_devpod_token_provider(broker_url: str = DEFAULT_BROKER_URL) -> TokenProvider:
    """Build a TokenProvider backed by the internal ``aiaas_auth`` package.

    The broker handles the Azure AD OAuth flow externally; ``auto_refresh``
    keeps the token valid for the process lifetime. Imported lazily so this
    module (and its tests) work outside the DevPod environment.
    """
    from aiaas_auth import AuthMode, AzureAuthClient  # type: ignore[import-not-found]

    auth = AzureAuthClient(broker_url=broker_url, mode=AuthMode.DEVPOD, auto_refresh=True)

    async def get_token() -> str:
        return await asyncio.to_thread(lambda: auth.authenticate_broker().access_token)

    return get_token


class LLMClient:
    """Async, concurrency-bounded, retrying client for the AIaaS gateway."""

    def __init__(
        self,
        token_provider: TokenProvider,
        base_url: str = DEFAULT_GATEWAY_BASE_URL,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        ca_bundle: Optional[str] = None,
        max_concurrency: int = MAX_CHAT_CONCURRENCY,
        max_retries: int = 5,
        backoff_base_s: float = 0.5,
        timeout_s: float = REQUEST_TIMEOUT_S,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if max_concurrency > MAX_CHAT_CONCURRENCY:
            raise ValueError(
                f"max_concurrency {max_concurrency} exceeds the AIaaS chat "
                f"ceiling ({MAX_CHAT_CONCURRENCY})"
            )
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._semaphore = asyncio.Semaphore(max_concurrency)
        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            # TLS verification stays enabled; an internal CA bundle can be
            # supplied via ca_bundle. verify=False is never used here.
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(timeout_s),
                verify=ca_bundle or True,
            )
            self._owns_client = True

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str = DEFAULT_CHAT_MODEL,
        tools: Optional[Sequence[Mapping[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ChatResponse:
        body: dict[str, Any] = {"model": model, "messages": list(messages)}
        if tools:
            body["tools"] = list(tools)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        payload = await self._request("POST", "/chat/completions", body)
        return ChatResponse.from_api(payload)

    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> list[list[float]]:
        """Embed texts, preserving input order in the returned vectors."""
        payload = await self._request(
            "POST", "/embeddings", {"model": model, "input": list(texts)}
        )
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    async def _request(
        self, method: str, path: str, body: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        last_exc: Optional[BaseException] = None
        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                try:
                    token = await self._token_provider()
                    response = await self._client.request(
                        method,
                        path,
                        json=body,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    await self._sleep_before_retry(attempt)
                    continue

                if response.status_code == 401 and attempt < self._max_retries:
                    # Token may have expired between provider cache and use;
                    # the provider (auto_refresh) yields a fresh one next call.
                    logger.warning("AIaaS gateway returned 401; refreshing token")
                    await self._sleep_before_retry(attempt)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    last_exc = LLMClientError(
                        f"AIaaS gateway {response.status_code}"
                    )
                    if attempt < self._max_retries:
                        await self._sleep_before_retry(
                            attempt, retry_after=response.headers.get("Retry-After")
                        )
                        continue
                    if response.status_code == 429:
                        raise RateLimitError(
                            "AIaaS gateway rate limit persisted after retries"
                        ) from last_exc
                    raise LLMClientError(
                        f"AIaaS gateway error {response.status_code} after retries"
                    ) from last_exc
                if response.status_code >= 400:
                    raise LLMClientError(
                        f"AIaaS gateway rejected request: {response.status_code}"
                    )
                return response.json()

        raise LLMClientError("AIaaS request failed after retries") from last_exc

    async def _sleep_before_retry(
        self, attempt: int, retry_after: Optional[str] = None
    ) -> None:
        if retry_after is not None:
            try:
                await asyncio.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        delay = self._backoff_base_s * (2**attempt) + random.uniform(0, 0.1)
        await asyncio.sleep(min(delay, 30.0))

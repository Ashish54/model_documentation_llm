"""vLLM-backed provider with ``direct`` and ``chat_only`` backends.

Auth note: the company deployment currently requires no API key. When the
company-provided auth package arrives, only ``_headers()`` changes — exactly
like the proxy this replaces.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from modelkb.core.config import VllmSettings
from modelkb.core.hashing import sha256_text
from modelkb.core.logging import get_logger
from modelkb.llm.base import (
    InteractionRecord,
    LlmCall,
    LlmOutcome,
    LlmValidationError,
    Recorder,
)
from modelkb.llm.json_emulation import build_json_instruction, extract_json_object

log = get_logger("llm")


class VllmProvider:
    name = "vllm"

    def __init__(
        self,
        settings: VllmSettings,
        *,
        recorder: Recorder | None = None,
        transport: httpx.BaseTransport | None = None,  # tests inject MockTransport
    ) -> None:
        if settings.backend not in ("chat_only", "direct"):
            raise ValueError(f"unknown vllm backend: {settings.backend}")
        self._settings = settings
        self.backend = settings.backend
        self._recorder = recorder
        self._client = httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.timeout_s,
            transport=transport,
        )

    # ------------------------------------------------------------------ #
    def complete_structured(self, call: LlmCall, response_model: type[BaseModel]) -> LlmOutcome:
        schema = response_model.model_json_schema()
        if self.backend == "direct":
            messages, extra = (
                call.messages,
                {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_model.__name__,
                            "schema": schema,
                        },
                    }
                },
            )
        else:  # chat_only: emulate structured output
            instruction = build_json_instruction(
                schema,
                requirement=f"Your task: {call.purpose}.",
            )
            messages = [*call.messages, {"role": "system", "content": instruction}]
            extra = {}

        validation_errors: list[Any] = []
        raw_text = ""
        started = time.monotonic()
        attempts = 0
        for attempt in range(2):  # initial + one JSON repair round-trip
            attempts = attempt + 1
            try:
                raw_text, request_payload, response_payload = self._chat(
                    messages,
                    max_tokens=call.max_tokens,
                    temperature=call.temperature,
                    extra=extra,
                )
            except httpx.HTTPError as exc:
                self._record(call, None, "error", [str(exc)], None, None, started)
                raise LlmValidationError(
                    f"LLM transport error: {exc}", errors=[str(exc)], raw_text=""
                ) from exc
            try:
                data = extract_json_object(raw_text)
                parsed = response_model.model_validate(data)
                outcome = LlmOutcome(
                    parsed=parsed,
                    raw_text=raw_text,
                    request_hash=sha256_text(json.dumps(request_payload, sort_keys=True)),
                    response_hash=sha256_text(raw_text),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    attempts=attempts,
                )
                self._record(
                    call,
                    outcome.response_hash,
                    "success",
                    [],
                    request_payload,
                    response_payload,
                    started,
                )
                return outcome
            except (ValueError, ValidationError) as exc:
                validation_errors.append(str(exc))
                log.warning(
                    "structured output invalid",
                    purpose=call.purpose,
                    attempt=attempts,
                    error=str(exc)[:200],
                )
                self._record(
                    call,
                    sha256_text(raw_text),
                    "validation_failed",
                    [str(exc)],
                    request_payload,
                    response_payload,
                    started,
                )
                # Repair: show the model its bad output once (chat_only only;
                # the direct backend's guided decoding should not produce this).
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw_text},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid: "
                            f"{str(exc)[:500]}\nRespond with ONLY the corrected JSON "
                            "object — no prose, no markdown fences."
                        ),
                    },
                ]

        raise LlmValidationError(
            f"structured output invalid after {attempts} attempts",
            errors=validation_errors,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------ #
    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float | None,
        extra: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        payload = {
            "model": self._settings.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": (self._settings.temperature if temperature is None else temperature),
            **extra,
        }
        last_error: httpx.HTTPError | None = None
        for _ in range(self._settings.max_retries + 1):
            try:
                response = self._client.post(
                    "/chat/completions", json=payload, headers=self._headers()
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"] or "", payload, data
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                log.warning("vllm request failed; retrying", error=str(exc)[:200])
        assert last_error is not None
        raise last_error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:  # company deployment needs none today
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        return headers

    def _record(
        self,
        call: LlmCall,
        response_hash: str | None,
        status: str,
        errors: list[Any],
        request_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None,
        started: float,
    ) -> None:
        if self._recorder is None:
            return
        self._recorder(
            InteractionRecord(
                purpose=call.purpose,
                provider=self.name,
                backend=self.backend,
                model=self._settings.model,
                prompt_version=call.prompt_version,
                request_hash=sha256_text(json.dumps(request_payload or {}, sort_keys=True)),
                response_hash=response_hash,
                status=status,
                validation_errors=errors,
                request_payload=request_payload,
                response_payload=response_payload,
                latency_ms=int((time.monotonic() - started) * 1000),
                extraction_run_id=call.extraction_run_id,
            )
        )

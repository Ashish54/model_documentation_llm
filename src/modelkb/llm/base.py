"""LLM provider abstraction.

The pipeline talks to ``LLMProvider.complete_structured`` and nothing else.
Two backends exist (see provider.py):

* ``direct``    — OpenAI-compatible server with native structured outputs
                  (vLLM guided decoding via response_format=json_schema).
* ``chat_only`` — chat-only deployment (the company gateway today): structured
                  output is emulated with JSON-only prompting, strict parsing,
                  and one repair round-trip.

Every call is auditable through the ``recorder`` callback (llm_interaction
rows): prompt version, model, request/response hashes, latency, and every
validation failure are evidence.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class LlmCall:
    purpose: str  # schema_proposal | section_classification | ...
    prompt_version: str
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    temperature: float | None = None  # None → provider default from settings
    extraction_run_id: uuid.UUID | None = None


@dataclass
class LlmOutcome:
    parsed: BaseModel
    raw_text: str
    request_hash: str
    response_hash: str
    latency_ms: int
    attempts: int


class LlmValidationError(Exception):
    """Structured output could not be produced/validated after all attempts."""

    def __init__(self, message: str, *, errors: list[Any], raw_text: str) -> None:
        super().__init__(message)
        self.errors = errors
        self.raw_text = raw_text


@dataclass
class InteractionRecord:
    """What the recorder persists per call (mirrors the llm_interaction table)."""

    purpose: str
    provider: str
    backend: str
    model: str
    prompt_version: str
    request_hash: str
    response_hash: str | None
    status: str  # success | validation_failed | error
    validation_errors: list[Any] = field(default_factory=list)
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    latency_ms: int | None = None
    extraction_run_id: uuid.UUID | None = None


Recorder = Callable[[InteractionRecord], None]


class LLMProvider(Protocol):
    name: str
    backend: str

    def complete_structured(self, call: LlmCall, response_model: type[BaseModel]) -> LlmOutcome: ...

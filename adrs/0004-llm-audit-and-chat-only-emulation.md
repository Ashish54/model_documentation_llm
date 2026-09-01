# ADR 0004: LLM provider abstraction, audit, and chat-only structured output

## Status

Accepted (milestone 3)

## Context

The regional vLLM endpoint is the only permitted LLM. Today the company
deployment is chat-only: no native tool calls or JSON-schema response format,
and no API key. Extraction still requires valid structured JSON.

## Decision

* **Provider abstraction** (`LLMProvider.complete_structured`) with two
  backends, env-selected (`KB_VLLM__BACKEND`):
  * `direct` — OpenAI-compatible server with native structured outputs
    (vLLM guided decoding via `response_format: json_schema`).
  * `chat_only` — emulates structured output: a JSON-schema instruction is
    appended, output is parsed tolerantly (markdown fences, balanced-brace
    scan), validated with Pydantic, and repaired once by showing the model
    its invalid output. Failure after the repair raises
    `LlmValidationError`. (Logic ported from the standalone proxy this
    package supersedes.)
* **Full audit in `llm_interaction`:** purpose, prompt version, provider,
  backend, model, request/response hashes, full payloads, latency, status
  (success|validation_failed|error), and every validation error. LLM inputs
  and outputs are treated as evidence in a governed system.
* **Auth seam.** No API key today; company auth plugs into
  `VllmProvider._headers()` (headers) or `_chat()` (package client) only.
* **LLM may not:** invent values/sources/relationships, calculate model
  outputs, overwrite history, or publish authoritative changes. Enforced by
  schema-required evidence IDs (milestone 4+) and validation tests (#6).

## Consequences

* Switching the real endpoint between chat-only and guided-decoding is a
  config change with no code impact.
* Every LLM decision is reproducible from the stored payload + prompt
  version + model identifier.

# Plan: Refine ARCHITECTURE.md for AIMart/vLLM reality + build plan

## Decisions locked this session
- Vector store: **pgvector**, hosted and accessed **locally** (not Azure AI Search). See [ADR-0002](adr/0002-pgvector-local-over-azure-ai-search.md).
- Embedding model: **confirmed** — `Qwen/Qwen3-Embedding-8B` on the same AIaaS gateway/DevPod broker auth as chat (separate deployment, GZ-WEU, A10 GPU, BF16). Context window is **8,192 tokens** — much smaller than the chat model's 262K, so chunking must respect this limit. Embedding dimension: **1024** (Matryoshka default for v1, tune after first ingestion test).
- Platform naming: **AIaaS** is the platform; **AIMart** is the gateway/portal within it. Use "AIaaS gateway" in all architecture docs.
- AIaaS auth: DevPod broker + Azure AD OAuth bearer token (`AzureAuthClient`, `AuthMode.DEVPOD`, auto-refresh) — service-level token, not per-user OBO. Per-user audit attribution happens in orchestrator-side logging, not at the AIaaS call. Same broker/gateway serves both chat (`Qwen/Qwen3.6-27B`) and embeddings (`Qwen/Qwen3-Embedding-8B`).
- Orchestrator: fully custom Python, no LangGraph/Semantic Kernel/Foundry — built around the OpenAI-compatible `tools=` function-calling API against `Qwen/Qwen3.6-27B`. See [ADR-0001](adr/0001-custom-orchestrator-over-managed-platform.md).
- Scenario definition: a **versioned, economist-authored forecast run** with fixed inputs and precomputed outputs; comparison operates on two whole scenarios with metrics as an output filter, never an input filter. The deterministic comparison workflow is an **existing internal Python package** owned by the economist/data team — `compare_scenarios` is a thin wrapper, not new logic.
- Chat surface: **v1 is a simple internal web UI**; Teams integration is a later phase.
- Session state: **in-memory per-process for v1**; durable history is a follow-on. See [ADR-0003](adr/0003-in-memory-session-state-v1.md).
- Guardrails: **system-prompt scoping only for v1**; no separate moderation/classifier model unless security/compliance review requires it.

## Part A — ARCHITECTURE.md edits

1. **§1 Purpose & Scope**: replace "internally hosted vLLM deployment, reached only through an internal Python client module — no public endpoint, no API keys" with: AIaaS gateway (OpenAI-compatible), reached via an internal `llm_client` module using DevPod broker OAuth bearer tokens (auto-refreshed), over the org's private gateway endpoint.
2. **§2 diagram**: relabel "vLLM client module (internal Python package, in-VNet gRPC/HTTP, no keys)" → "AIaaS client (OpenAI SDK + DevPod broker auth)"; relabel "Internal vLLM deployment" → "AIaaS gateway → Qwen/Qwen3.6-27B (chat) + Qwen/Qwen3-Embedding-8B (embeddings)".
3. **§3.1 Orchestrator**: note native function/tool-calling + structured outputs are supported by the model, so the tool loop uses the standard `tools=` parameter rather than hand-rolled parsing; correct the auth description to bearer-token (broker), not mTLS/network-only.
4. **§3.3 Grounding knowledge**: vector store = pgvector (local); embeddings via the confirmed `Qwen/Qwen3-Embedding-8B` deployment on the same AIaaS gateway (separate model ID from chat). Note the **8,192-token input limit** on chunk size (well below the chat model's 262K), embedding dimension fixed at **1024** for v1 (Matryoshka default, tune later), and consistent text normalization + `query:`/`document:` prefixing across ingestion and runtime search.
5. **§3.5 Auth & access control**: rewrite the orchestrator→LLM path — service calls AIaaS with a DevPod-broker service token (not per-user OBO); per-user audit attribution is handled in orchestrator-side logging.
6. **§5 Non-Functional**: replace "fixed GPU infra" cost/perf framing with actual constraints from vllm_specs.md: max 15 RPS, max concurrency 64 (chat)/100 (small prompt), P95 latency SLO 45s, min success rate 0.95, per-token billing (~$0.247/1M blended). Add guidance: bounded concurrency/backoff at orchestrator, multi-hop tool-loop latency can stack past the 45s single-call SLO — plan streaming/status UI.
7. **§6 Open Decisions**: remove resolved items (vector store, embedding model, chat surface → web UI for v1, moderation → system-prompt only for v1, per-user attribution → service-level token + orchestrator-side logging, embedding dimension → 1024). Remaining open: exact internal scenario API contracts, hosting topology for the orchestrator/ingestion worker, network path to the AIaaS gateway.

## Part B — Build plan (implementation, after doc refinement)

**Steps**
1. **LLM client wrapper** (`llm_client.py`) — wrap `AzureAuthClient`/DevPod broker + OpenAI-compatible client; expose `chat(model="Qwen/Qwen3.6-27B")` and `embeddings(model="Qwen/Qwen3-Embedding-8B")` (two distinct model IDs on the same gateway/broker token); auto-refresh token; retries+backoff; bounded concurrency (semaphore under the 15 RPS/64-concurrency ceiling); proper CA verification (no `verify=False` in prod).
2. **Deterministic tool implementations** — `list_scenarios`, `get_scenario_data` (call internal scenario APIs), `compare_scenarios` (thin wrapper around the **existing** economist-team comparison Python package — no new comparison logic). Each returns a structured `ToolResult` dict per §3.6 contract. *Parallel with Step 1.*
3. **Tool Registry** — common `Tool` interface (name, description, JSON Schema args, async `call(args, context)`), static in-code registry built at startup. *Depends on Step 2.*
4. **Orchestrator core loop** — message-history-per-session loop (in-memory dict, keyed by session ID, per ADR-0003) using `client.chat.completions.create(model="Qwen/Qwen3.6-27B", tools=SCHEMAS, ...)`; dispatch `tool_calls` via registry; append tool result messages; loop to final assistant message. *Depends on Steps 1 & 3.*
5. **RAG pipeline (pgvector, local)** — schema for chunks (doc id, SharePoint URL, site, modified ts, author, version, ACL field, `vector(1024)` column); chunk size must fit within the embedding model's **8,192-token** input limit; ingestion worker reusing Graph webhook + delta-sync design (§3.4) but embedding via `llm_client.embeddings(model="Qwen/Qwen3-Embedding-8B")` (with `document:` prefix) and upserting into local pgvector by stable key; `search_knowledge_base` tool embeds the query with the `query:` prefix and does pgvector similarity search + ACL `security_filter` using caller's Entra group claims.
6. **AuthN/Z** — Entra ID SSO + OBO for scenario APIs and pgvector ACL filter (unchanged from §3.5); AIaaS calls use the service-level broker token, with orchestrator-side per-user logging for audit.
7. **Guardrails** — system-prompt scoping + allowlist-only registry only; no separate moderation model in v1.
8. **Observability** — log tool name+version, AIaaS model id, token usage (`completion.usage`), latency, retry counts, and per-user attribution (which user triggered which tool calls).
9. **Deployment** — package orchestrator as a containerized FastAPI service exposing a chat endpoint for a simple internal web UI (v1); ingestion worker as a separate scheduled/event process.

**Relevant files**
- [ARCHITECTURE.md](ARCHITECTURE.md) — apply Part A edits.
- New: `llm_client.py`, `tools/list_scenarios.py`, `tools/get_scenario_data.py`, `tools/compare_scenarios.py`, `tools/search_knowledge_base.py`, `tool_registry.py`, `orchestrator.py`, `ingestion/webhook_handler.py`, `ingestion/delta_sync.py`, `ingestion/embedder.py`, `db/pgvector_schema.sql`.

**Verification**
1. Unit tests per tool: JSON Schema conformance + mocked upstream calls.
2. Integration test: full tool-calling round trip against AIMart in a lower env using a real `compare_scenarios` case.
3. Load test: concurrent sessions against the 15 RPS/64-concurrency ceiling, confirm backoff/retry and graceful degradation (not silent failure).
4. RAG ACL test: user without SharePoint access to a source doc must not see its chunks in results; citations render correctly.
5. Security check: no `verify=False`, tokens never logged, internal CA trust configured.

## Further Considerations
1. **Exact scenario API contracts** for `list_scenarios` / `get_scenario_data` (auth method, request/response schema) are still unconfirmed — coordinate with the economist/data team before starting Step 2.
2. **Teams as a chat surface** is a later phase once the core loop is validated on the web UI.
3. **Durable session storage** becomes a follow-on if usage data shows users returning to past conversations.
4. **Moderation step** — revisit only if security/compliance review flags system-prompt-only scoping as insufficient.

# Economic Scenario Comparison Chatbot — Architecture Design

## 1. Purpose & Scope

A scoped chatbot that lets users compare two economic scenarios. It is **not** a general-purpose assistant:

- It only answers questions about listing, selecting, and comparing economic scenarios and interpreting the results.
- Scenario numbers come from internal APIs + a deterministic Python workflow — never from the LLM or from SharePoint.
- SharePoint content is used **only** as grounding knowledge (definitions, methodology, assumptions) to help the LLM explain results — never as a source of scenario data.
- All LLM and embedding inference goes through the **AIaaS gateway** (OpenAI-compatible API, reached over the org's private gateway endpoint), via an internal `llm_client` module that authenticates with DevPod broker OAuth bearer tokens (auto-refreshed) — no public endpoint, no static API keys.

## 2. High-Level Architecture

```
                         ┌─────────────────────────────┐
                         │   User (Web chat, v1)       │
                         └───────────────┬─────────────┘
                                           │
                                 ┌─────────▼─────────┐
                                 │   Orchestrator      │  Custom Python service, native
                                 │  (LLM + tool router)│  tools= function-calling loop,
                                 └───┬────────┬────────┘  system prompt scopes to use case
                                     │        │
                                     │        └──────────────────┐
                                     │                            │
                           ┌─────────▼──────────┐                 │
                           │  AIaaS client       │                 │
                           │  (OpenAI SDK +      │                 │
                           │   DevPod broker     │                 │
                           │   auth)             │                 │
                           └─────────┬──────────┘                 │
                                     │                             │
                           ┌─────────▼──────────┐                  │
                           │  AIaaS gateway      │                  │
                           │  - Qwen/Qwen3.6-27B  │                 │
                           │    (chat)            │                 │
                           │  - Qwen/Qwen3-       │                 │
                           │    Embedding-8B      │                 │
                           │    (embeddings)      │                 │
                           └────────────────────┘                  │
                     ┌───────────────┘        └────────────────┐   │
                     │                                          │   │
           ┌─────────▼──────────┐                    ┌──────────▼───▼───────┐
           │  RAG Tool           │                    │  Scenario Tools       │
           │  (SharePoint        │                    │  - list_scenarios()   │
           │   grounding index)  │                    │  - get_scenario(id)   │
           └─────────┬──────────┘                    └──────────┬───────────┘
                     │                                          │
           ┌─────────▼──────────┐                    ┌──────────▼───────────┐
           │ pgvector store      │                    │ Internal Scenario API │
           │ (local; vector +    │                    │ (owned by economist   │
           │  ACL filtered)      │                    │  team / data platform)│
           └─────────┬──────────┘                    └──────────┬───────────┘
                     │                                          │
           ┌─────────▼──────────┐                                │
           │ Ingestion Pipeline  │                                │
           │ (Graph webhooks +   │                                │
           │  delta sync)        │                                │
           └─────────┬──────────┘                    ┌──────────▼───────────┐
                     │                                │ Comparison Workflow   │
           ┌─────────▼──────────┐                     │ (existing economist-  │
           │ SharePoint site     │                     │  team Python package) │
           │ (economist KB)      │                     └──────────┬───────────┘
           └────────────────────┘                                 │
                                                        Comparison result (structured)
                                                                   │
                                                        back to Orchestrator → LLM
                                                        composes explanation using
                                                        result + retrieved KB context
```

`RAG Tool` and `Scenario Tools` above are the two tools registered at launch. Both plug into the orchestrator through a common **Tool Registry** (3.1) — the extension point for adding future tools/data sources without changing the orchestrator's core loop.

## 3. Components

### 3.1 Orchestrator (agentic layer)
- A **fully custom Python orchestrator** — no LangGraph, Semantic Kernel, or Azure AI Foundry Agent Service (see [ADR-0001](adr/0001-custom-orchestrator-over-managed-platform.md)) — with a fixed system prompt, driven by a **Tool Registry** rather than a hardcoded toolset (see 3.6 for the extension contract). At launch the registry holds:
  - `list_scenarios()` → calls internal API
  - `get_scenario_data(scenario_id)` → calls internal API
  - `compare_scenarios(scenario_a, scenario_b, options)` → calls the deterministic Python comparison workflow
  - `search_knowledge_base(query)` → calls the pgvector index (RAG) over the SharePoint index
- The chat model (`Qwen/Qwen3.6-27B`) natively supports function/tool calling and structured outputs, so the tool loop uses the standard OpenAI-compatible **`tools=` parameter** and consumes `tool_calls` from the response — no hand-rolled output parsing.
- All chat/completion and embedding calls go through the **internal `llm_client` module**: an OpenAI-compatible client pointed at the AIaaS gateway, authenticated with a DevPod broker OAuth bearer token that auto-refreshes (broker handles the Azure AD OAuth flow). This is a **service-level token**, not per-user OBO — per-user audit attribution happens in orchestrator-side logging (see 3.5).
- The LLM never computes the comparison itself; it always calls `compare_scenarios` and treats the returned structured result as ground truth to narrate.
- Scoping/guardrails (v1):
  - System prompt restricts the assistant to the scenario-comparison domain and instructs refusal of unrelated requests.
  - Tool access is hard-restricted at the orchestration layer (no general web/code tools) — the registry is an *allowlist*, not a plugin free-for-all; adding a tool still requires an explicit registration + review step (3.6).
  - Retrieved SharePoint content is treated as data, not instructions (stated in the system prompt and in how retrieved chunks are presented to the model).
  - **No separate moderation/classifier model in v1** — system-prompt scoping plus the allowlist registry only. Revisit only if the security/compliance review flags this as insufficient (§6).

### 3.2 Scenario data path (deterministic, non-RAG)
- `list_scenarios` / `get_scenario_data` call the existing internal scenario APIs directly (owned by the economist/data team) — no caching of scenario values in the vector store, so figures are always live.
- `compare_scenarios` is a **thin wrapper around the existing economist/data-team comparison Python package** — no new comparison logic is built here. That package performs the actual calculation (deltas, growth rates, variance decomposition, etc.) and returns a structured JSON result (numbers + labeled fields), not prose.
- The LLM receives this structured JSON and is responsible only for **explaining/contextualizing** it, optionally pulling in relevant KB passages (e.g., "why does the model assume X") via the RAG tool.

### 3.3 Grounding knowledge (RAG over SharePoint)
- **Index**: **pgvector**, hosted and accessed **locally** (see [ADR-0002](adr/0002-pgvector-local-over-azure-ai-search.md)) for the economist KB — vector similarity search with ACL/permission metadata as filterable fields.
- **Embeddings**: the confirmed **`Qwen/Qwen3-Embedding-8B`** deployment on the **same AIaaS gateway** and DevPod broker auth as chat (a separate model ID from the chat model), called through the same `llm_client` module — no external embedding API.
  - The embedding model's context window is **8,192 tokens** — far below the chat model's 262K — so chunking must keep every chunk within this limit.
  - Embedding dimension is fixed at **1024** for v1 (Matryoshka default; tune after the first ingestion test).
  - Apply **consistent text normalization** (casing/whitespace) and **`query:` / `document:` prefixing** across ingestion and runtime search so indexed and query embeddings live in the same space.
- **Metadata per chunk**: source document ID, SharePoint URL, site/library, last modified timestamp, author, version, and ACL/permission info (see 3.4) — used for citation and traceability in every answer that uses KB content.

### 3.4 Ingestion & incremental sync mechanism
This is the piece that keeps grounding knowledge current without full manual re-indexing:

1. **Change detection**: Register a Microsoft Graph webhook subscription on the SharePoint document library/site (`/sites/{id}/drive/root` or list resource). Graph notifies an endpoint on create/update/delete. Subscriptions expire (max ~30 days for drives) so a renewal timer job is required.
2. **Reconciliation**: Because webhooks can miss events, run a **Graph delta query** (`/drive/root/delta`) on a schedule (e.g., every 15–30 min) as the source of truth for what changed since the last sync token — this is idempotent and self-healing even if a webhook was missed.
3. **Ingestion worker** (timer- and event-triggered):
   - New/updated file → download → parse (reuse existing parsers, e.g. PDF/Office parsing) → chunk (within the 8,192-token embedding input limit) → embed via `llm_client.embeddings(model="Qwen/Qwen3-Embedding-8B")` with the `document:` prefix → **upsert** into pgvector by a stable document key (SharePoint item ID + chunk index).
   - Deleted/moved file → **delete** corresponding chunks from the index by that same key.
   - Store the last delta token per site in a small state store so each run resumes from where it left off.
4. **Access control (ACL) sync**: Read each item's permissions via Graph (`/items/{id}/permissions`), store the resolved group/user list as a filterable field on each chunk, and apply a `security_filter` on queries using the requesting user's Entra ID group membership (token-based row-level security).
   - This ensures the chatbot never surfaces content to a user who doesn't have SharePoint access to the source document.
5. **Source traceability**: Every RAG-grounded answer includes citations (document title + SharePoint link) so users can verify against the original economist-authored source.

### 3.5 Authentication & access control
- User signs in via Entra ID (SSO); the orchestrator uses **on-behalf-of (OBO)** token flow to call:
  - Internal scenario APIs (respecting whatever role-based access those APIs already enforce).
  - The pgvector index with the user's group claims applied as a security filter (per 3.4).
- The orchestrator → AIaaS gateway path is **not** per-user OBO: the service authenticates with a **DevPod-broker service token** (Azure AD OAuth, auto-refreshed via `AzureAuthClient`/`AuthMode.DEVPOD`). Both the chat and embedding model calls use this same broker/gateway token. **Per-user audit attribution is handled in orchestrator-side logging** (which user triggered which AIaaS calls and tool calls), not at the AIaaS call itself.
- Other service-to-service calls (ingestion worker → Graph API, → pgvector) use a managed identity with least-privilege permissions (`Sites.Read.All` or scoped site permissions, not full tenant read).

### 3.6 Tool Registry & extensibility pattern
The registry is what lets future components (new data domains, new comparison types, new KB sources) be added without touching the orchestrator's tool-loop code:

- **Tool contract**: every tool implements a common interface — `name`, `description`, a JSON Schema for its arguments, and an async `call(args, context) -> ToolResult` method. `context` carries the authenticated user's identity/claims (for OBO calls per 3.5) and a request/correlation ID (for audit logging per §5). `ToolResult` is a structured payload (not raw prose), consistent with the LLM only ever narrating structured data (3.2).
- **Registration**: tools are registered explicitly in a **static in-code registry built at orchestrator startup** (single deployable, reviewed allowlist) rather than special-cased in the orchestrator's dispatch logic. Registering a tool is a reviewed, deliberate step — the registry is an allowlist, not open plugin loading.
- **Versioning**: each tool declares a `version` string; the orchestrator logs `tool name + version` on every call, alongside the existing comparison-workflow and AIaaS model-id logging (§5 Versioning/Auditability). This lets a tool's behavior evolve (e.g. `compare_scenarios` v2 adding a new metric) without breaking audit trails for older calls.
- **Isolation**: each tool owns its own upstream client (internal API, vector store, future systems) and error handling; a failing or slow tool degrades gracefully (timeout + a "tool unavailable" result the LLM can narrate) rather than taking down the orchestrator loop.
- **Testability**: new tools ship with a schema-conformance test (args match declared JSON Schema, `ToolResult` shape matches contract) plus their own unit tests against the upstream system, independent of the orchestrator — so a new tool can be developed and validated in isolation before registration.
- **Scoping stays enforced per tool, not just globally**: the system prompt's domain restriction applies uniformly to whatever is in the registry, so adding a tool never silently widens what the assistant will attempt to do outside the scenario-comparison domain.

## 4. Request Flow Example

1. User: "Compare Scenario A vs Scenario B for FY26 GDP growth."
2. Orchestrator calls `list_scenarios()` if needed to resolve names → IDs.
3. Orchestrator calls `compare_scenarios(A, B)` → the existing economist-team comparison package returns structured deltas/metrics.
4. Orchestrator calls `search_knowledge_base("GDP growth assumptions methodology")` → query is embedded via `llm_client` against `Qwen/Qwen3-Embedding-8B` (with the `query:` prefix), then matched against pgvector → retrieves relevant, permission-filtered chunks with citations.
5. Orchestrator sends the assembled context (structured comparison result + retrieved chunks + conversation) to `Qwen/Qwen3.6-27B` on the AIaaS gateway via `llm_client`.
6. LLM composes a response: narrates the structured comparison result, references methodology/assumptions from retrieved KB chunks with citations, and stays within the comparison-explanation scope.

## 5. Non-Functional Considerations
- **Freshness**: delta-sync interval (e.g., 15–30 min) defines the KB staleness SLA; document this to users/stakeholders.
- **Auditability**: log every tool call (scenario IDs compared, KB chunks retrieved with source links) per conversation for traceability/compliance, including per-user attribution for AIaaS calls (which are made under a service-level token, per 3.5).
- **Versioning**: the comparison workflow should be versioned; log which version produced a given result. Also log the AIaaS model ID used for each chat and embedding call, since there's no managed model registry doing this automatically.
- **Cost/perf (AIaaS gateway constraints, from the AIMart catalog)**: capacity is governed by the platform consumption plan, not by infra we control. Planning figures: **max 15 RPS**, **max concurrency 64** (chat) / **100** (small prompt), **P95 latency SLO 45s**, **min success rate 0.95**, per-token billing (**~$0.247/1M tokens blended**). Implications:
  - Enforce **bounded concurrency and retry-with-backoff at the orchestrator** (semaphore under the 15 RPS / 64-concurrency ceiling); respect rate-limit responses; never fan out unbounded parallel requests.
  - A multi-hop tool loop (e.g. list → compare → search → final answer) issues several sequential model calls, so **end-to-end latency can stack well past the 45s single-call SLO** — plan a streaming or status-indicating UI rather than a bare blocking request.
  - Only re-embed changed/added chunks (never full re-index) to keep ingestion token spend down as the KB grows.
- **Observability**: since there's no Azure AI Foundry/Application Insights integration by default, instrument the orchestrator and ingestion worker directly — tool name+version, AIaaS model ID, token usage (from `completion.usage`), per-call latency, retry counts, per-user attribution, embedding throughput, webhook misses, delta sync failures — and ship to whatever internal metrics/logging stack is standard.

## 6. Open Decisions to Confirm
- Exact internal scenario API contracts for `list_scenarios` / `get_scenario_data` (auth method, request/response schema) — coordinate with the economist/data team.
- Hosting topology for the orchestrator and ingestion worker (container platform, scaling model).
- Network path from the orchestrator/ingestion worker to the AIaaS gateway (private endpoint resolution, egress rules, internal CA trust configuration).

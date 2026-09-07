# Scenario Comparison Chatbot — Implementation

Implementation of the build plan in [docs/plan.md](docs/plan.md) (Part B).
Architecture and domain language: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[CONTEXT.md](CONTEXT.md).

## Layout

| Path | Purpose |
|---|---|
| `llm_client.py` | AIaaS gateway client: DevPod broker OAuth (auto-refresh), OpenAI-compatible chat + embeddings, retries/backoff, semaphore under the 15 RPS / 64-concurrency ceiling, TLS verification always on (internal CA via `ca_bundle`). |
| `tools/` | Allowlisted tools per the §3.6 contract: `list_scenarios`, `get_scenario_data`, `compare_scenarios` (thin wrapper around the existing economist-team comparison package), `search_knowledge_base`. |
| `tool_registry.py` | Static in-code registry + dispatch with audit logging (tool name+version, model id, latency, per-user attribution). |
| `orchestrator.py` | Custom `tools=` function-calling loop against `Qwen/Qwen3.6-27B`; in-memory per-process sessions (ADR-0003); system-prompt scoping (v1 guardrails). |
| `ingestion/` | Graph delta-sync worker (`delta_sync.py`), webhook handler (`webhook_handler.py`), chunking/embedding with `document:`/`query:` prefixes (`embedder.py`). |
| `vector_store.py` | `VectorStore` contract + `PgVectorStore` (local pgvector, ACL security filter in SQL) + `InMemoryVectorStore` for tests/dev. |
| `db/pgvector_schema.sql` | KB chunks table (`vector(1024)`, ACL array, HNSW + GIN indexes) and delta-token state table. |
| `api.py` | FastAPI chat service for the v1 internal web UI. |

## Develop

```bash
python3.14 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio httpx fastapi
.venv/bin/python -m pytest          # 55 tests
```

## Run (requires the internal environment)

```bash
export AIAAS_GATEWAY_BASE_URL=...   # defaults to the AIMart gateway
export AIAAS_CA_BUNDLE=/path/to/internal-ca.pem
export SCENARIO_API_BASE_URL=...
export PGVECTOR_DSN=postgresql://...
psql "$PGVECTOR_DSN" -f db/pgvector_schema.sql
.venv/bin/uvicorn 'api:create_app' --factory
```

`aiaas_auth` (DevPod broker auth) and `scenario_comparison` (economist-team
comparison workflow) are internal packages, imported lazily — tests and local
dev work without them.

## Verification status (plan §Verification)

1. Unit tests per tool (schema conformance + mocked upstreams) — ✅ `tests/test_tools.py`
2. Full tool-calling round trip — ✅ against a scripted fake model (`tests/test_orchestrator.py`); **live AIMart lower-env round trip still to be run in the internal environment**
3. Load test against the 15 RPS / 64-concurrency ceiling — **requires the internal environment** (client-side bounding is unit-tested in `tests/test_llm_client.py`)
4. RAG ACL test (no leakage across SharePoint permissions; citations) — ✅ `tests/test_tools.py::test_search_applies_acl_security_filter`
5. Security check (no `verify=False`, tokens never logged, CA trust configurable) — ✅ AST-level check in `tests/test_llm_client.py`

## Open before production (plan §Further Considerations)

- Confirm the exact scenario API contracts with the economist/data team, then finalize `tools/scenario_api.py::HttpScenarioAPIClient`.
- Wire the tenant JWKS claims decoder into `api.create_app(claims_decoder=...)`.
- Ingestion scheduling (delta-sync timer, webhook subscription renewal) is deployment config, not code.

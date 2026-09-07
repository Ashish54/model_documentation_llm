# Runbook — Scenario Comparison Chatbot

Step-by-step procedures to run the app and exercise each feature. (a.k.a. "runback")
Prerequisites: macOS with Homebrew Python 3.14 (`/usr/local/opt/python@3.14/bin/python3.14`), repo checked out, access to the internal network (AIaaS gateway, Graph API, scenario APIs, pgvector host).

---

## 1. First-time setup

```bash
cd plausibility-ai-chatbot-design

# 1.1 Create the virtualenv (Python 3.14 — required by pyproject.toml)
/usr/local/opt/python@3.14/bin/python3.14 -m venv .venv

# 1.2 Install dependencies
.venv/bin/pip install httpx fastapi uvicorn          # runtime
.venv/bin/pip install asyncpg                        # pgvector store (db extra)
.venv/bin/pip install pytest pytest-asyncio          # tests only

# 1.3 Internal packages (available only inside the org environment):
#     - aiaas_auth          (DevPod broker auth — lazily imported by llm_client)
#     - scenario_comparison (economist-team comparison workflow)
.venv/bin/pip install aiaas_auth scenario_comparison  # via internal index
```

## 2. Verify the install (offline, no internal access needed)

```bash
.venv/bin/python -m pytest -q        # expect: 55 passed
```

## 3. Configure the database (pgvector, local)

```bash
# 3.1 Start postgres with the pgvector extension available, then:
createdb kb_index

# 3.2 Apply the schema (chunks table, vector(1024), HNSW + GIN indexes, sync state)
psql postgresql://localhost/kb_index -f db/pgvector_schema.sql
```

## 4. Configure environment variables

```bash
# AIaaS gateway (defaults to the AIMart prod gateway if unset)
export AIAAS_GATEWAY_BASE_URL="https://gateway.aimart-apim-prod.azpriv-cloud.ubs.net/aiaas/v1"

# Internal CA bundle for TLS verification (never disable verification)
export AIAAS_CA_BUNDLE="/path/to/internal-ca.pem"
export SCENARIO_API_CA_BUNDLE="/path/to/internal-ca.pem"

# Internal scenario API (economist/data team — contract per ARCHITECTURE §6)
export SCENARIO_API_BASE_URL="https://scenario-api.internal/"

# pgvector
export PGVECTOR_DSN="postgresql://localhost/kb_index"

# SharePoint source of the economist KB
export KB_SITE_ID="your-sharepoint-site-id"
```

## 5. Run the chat service (v1 web UI backend)

```bash
.venv/bin/uvicorn 'api:create_app' --factory --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl -s http://localhost:8000/health        # {"status":"ok"}
```

> Note: production runs must pass the tenant JWKS claims decoder
> (`create_app(claims_decoder=...)`) so Entra tokens are validated. Without it,
> `/chat` returns 503 by design.

---

## 6. Using the features

All chat calls need an Entra ID bearer token (SSO). The token's group claims
drive the pgvector ACL security filter, and it is used on-behalf-of for the
scenario APIs.

### 6.1 Start a conversation (new session)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What scenarios are available?"}'
```

Response:

```json
{"session_id": "ab12cd34...", "answer": "The available scenarios are: ..."}
```

Save the `session_id` — the orchestrator keeps history in memory per process
(ADR-0003); a restart clears sessions.

### 6.2 Continue a conversation (existing session)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "ab12cd34...", "message": "Tell me more about the second one"}'
```

### 6.3 Compare two scenarios (deterministic workflow)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Compare Baseline FY26 vs Downside FY26 for GDP growth"}'
```

Behind the scenes the model calls `list_scenarios` → `compare_scenarios`
(existing economist-team package) and narrates the structured result. Metrics
act as an output filter, never an input filter.

### 6.4 Ask a grounding question (RAG over SharePoint KB)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What methodology does the model use for GDP assumptions?"}'
```

The answer includes citations (document title + SharePoint link). Documents
the user cannot access in SharePoint never appear (ACL filter on Entra group
claims — verified by `tests/test_tools.py::test_search_applies_acl_security_filter`).

### 6.5 Guardrail behavior (scoping)

Ask anything off-domain (`"write me a poem"`, `"what's the weather"`):
the system prompt instructs refusal with a redirect to scenario comparison.
No moderation model runs in v1 — scoping is system prompt + tool allowlist only.

---

## 7. Create the RAG index from scratch

End-to-end: empty database → searchable, ACL-trimmed knowledge index.
(Concepts: ARCHITECTURE §3.3/§3.4; code: `ingestion/`, `vector_store.py`.)

### 7.1 Provision the store

Complete §3 (database + schema). Sanity-check the extension and dimension:

```bash
psql "$PGVECTOR_DSN" -c "SELECT extname FROM pg_extension WHERE extname='vector';"
psql "$PGVECTOR_DSN" -c "\d kb_chunks"     # embedding column must be vector(1024)
```

The dimension is fixed at **1024** for v1 (Qwen3-Embedding-8B Matryoshka
default). Changing it later requires re-embedding everything.

### 7.2 Verify the embedding path before ingesting

```bash
.venv/bin/python - <<'EOF'
import asyncio, os
from llm_client import LLMClient, make_devpod_token_provider, DEFAULT_EMBEDDING_MODEL
from ingestion.embedder import Embedder

async def main():
    llm = LLMClient(make_devpod_token_provider(),
                    ca_bundle=os.environ.get("AIAAS_CA_BUNDLE"))
    embedder = Embedder(llm, model=DEFAULT_EMBEDDING_MODEL)
    vec = await embedder.embed_query("gdp methodology")
    assert len(vec) == 1024, len(vec)
    print("embedding OK — dimension", len(vec))

asyncio.run(main())
EOF
```

This proves broker auth, gateway reachability, the model ID, and the
`query:` prefixing in one shot. Do not continue until this passes.

### 7.3 Initial bulk ingestion (first full crawl)

The delta-sync worker doubles as the bulk loader: with **no stored delta
token**, the Graph delta query returns every item in the library.

```bash
.venv/bin/python - <<'EOF'
import asyncio, os
from ingestion.delta_sync import DeltaSync, InMemoryStateStore
from ingestion.embedder import Embedder
from llm_client import LLMClient, make_devpod_token_provider, DEFAULT_EMBEDDING_MODEL
from vector_store import PgVectorStore
# from your_graph import GraphDeltaClient   # Graph client (managed identity, Sites.Read.All)
# from your_parsers import Parser           # PDF/Office → plain text

async def main():
    llm = LLMClient(make_devpod_token_provider(),
                    ca_bundle=os.environ.get("AIAAS_CA_BUNDLE"))
    sync = DeltaSync(
        graph=...,                 # GraphDeltaClient impl
        parser=...,                # Parser impl
        embedder=Embedder(llm, model=DEFAULT_EMBEDDING_MODEL),
        store=PgVectorStore(os.environ["PGVECTOR_DSN"]),
        state=InMemoryStateStore(),  # empty state => full crawl; use ingestion_state table in prod
    )
    stats = await sync.run_once(os.environ["KB_SITE_ID"])
    print(stats)  # {'upserted_docs': N, 'deleted_docs': 0, 'chunks': M}

asyncio.run(main())
EOF
```

Per document, the worker: downloads → parses → normalizes → chunks (each
chunk safely within the embedding model's **8,192-token** input limit) →
embeds with the **`document:` prefix** → upserts into pgvector keyed by
(SharePoint item ID + chunk index).

### 7.4 Verify ACLs were captured

Every chunk must carry its resolved Entra group list, or the security filter
will hide it from everyone:

```bash
psql "$PGVECTOR_DSN" -c \
  "SELECT doc_id, acl_groups FROM kb_chunks WHERE acl_groups = '{}' LIMIT 5;"
```

Empty `{}` rows mean the Graph `/items/{id}/permissions` resolution step in
your `GraphDeltaClient` isn't populating `DriveItem.acl_groups` — fix that
before users rely on the index.

### 7.5 Verify retrieval end-to-end

```bash
# a) Row count and a sample
psql "$PGVECTOR_DSN" -c "SELECT count(*) FROM kb_chunks;"
psql "$PGVECTOR_DSN" -c "SELECT title, chunk_index, left(content, 80) FROM kb_chunks LIMIT 3;"

# b) Similarity search with an ACL filter, through the same code the tool uses
.venv/bin/python - <<'EOF'
import asyncio, os
from llm_client import LLMClient, make_devpod_token_provider, DEFAULT_EMBEDDING_MODEL
from ingestion.embedder import Embedder
from vector_store import PgVectorStore

async def main():
    llm = LLMClient(make_devpod_token_provider(),
                    ca_bundle=os.environ.get("AIAAS_CA_BUNDLE"))
    embedder = Embedder(llm, model=DEFAULT_EMBEDDING_MODEL)
    store = PgVectorStore(os.environ["PGVECTOR_DSN"])
    vec = await embedder.embed_query("gdp growth methodology")
    hits = await store.similarity_search(
        vec, acl_groups=frozenset({"grp-economists"}), top_k=5)
    for h in hits:
        print(round(h.score, 3), h.title, h.source_url)

asyncio.run(main())
EOF
```

Then a negative ACL check: re-run with a group that has **no** access to some
source document and confirm its chunks are absent. Finally ask the same
question through `/chat` (§6.4) and confirm the answer carries citations.

### 7.6 Keep the index fresh

- **Delta sync** on a schedule (every 15–30 min) — this interval is the KB
  staleness SLA. See §8.1. Only changed/added chunks are re-embedded.
- **Graph webhook** (optional, low latency) — see §8.2; webhooks only trigger
  a delta run, so missed events self-heal.
- **Deletes**: removing a file from SharePoint removes its chunks on the next
  sync (keyed by item ID).

### 7.7 Rebuild / reset the index

```bash
psql "$PGVECTOR_DSN" -c "TRUNCATE kb_chunks; DELETE FROM ingestion_state;"
# then re-run 7.3 (empty state => full crawl)
```

---

## 8. Run the ingestion worker (ongoing operations)

### 8.1 One-shot delta sync (also the scheduled form)

Same script as §7.3 — with a stored token it processes only changes:

```bash
.venv/bin/python - <<'EOF'
import asyncio, os
from ingestion.delta_sync import DeltaSync, InMemoryStateStore
from ingestion.embedder import Embedder
from llm_client import LLMClient, make_devpod_token_provider, DEFAULT_EMBEDDING_MODEL
from vector_store import PgVectorStore

async def main():
    llm = LLMClient(make_devpod_token_provider(),
                    ca_bundle=os.environ.get("AIAAS_CA_BUNDLE"))
    sync = DeltaSync(
        graph=..., parser=...,
        embedder=Embedder(llm, model=DEFAULT_EMBEDDING_MODEL),
        store=PgVectorStore(os.environ["PGVECTOR_DSN"]),
        state=...,  # backed by the ingestion_state table so runs resume
    )
    print(await sync.run_once(os.environ["KB_SITE_ID"]))

asyncio.run(main())
EOF
```

Each run resumes from the stored delta token: new/updated files are chunked,
embedded with the `document:` prefix, and upserted by (item ID + chunk
index); deleted files remove their chunks.

### 8.2 Graph webhook endpoint (optional low-latency trigger)

- Subscription creation: Graph calls the endpoint with
  `?validationToken=...` — `WebhookHandler.handle_validation` echoes it back
  (HTTP 200, text/plain).
- Notifications: POSTed payloads trigger a delta-sync per affected site.
  Configure the shared `clientState` secret so spoofed notifications are dropped.
- Renew the subscription before expiry (max ~30 days for drives) via a timer
  job — scheduling is deployment config.

---

## 9. Observability / where to look when something's wrong

Structured logs go to stderr (standard logging). Key events:

| Log event | Meaning |
|---|---|
| `aiaas_chat_call model=... prompt_tokens=... latency_ms=...` | every model call: model id, token usage, latency, user attribution |
| `tool_call tool=... version=... status=... latency_ms=...` | every tool dispatch (audit trail §5) |
| `tool_call_rejected ... reason=not_registered` | model asked for a non-allowlisted tool |
| `tool_call_timeout` | tool exceeded 30s; the LLM gets a narratable "tool unavailable" |
| `tool_loop_exhausted` | more than 8 tool rounds; user gets a graceful fallback |
| `delta_sync site=... stats=...` | ingestion run summary |

Common issues:

- **401 from the gateway** — broker token expired; the client refreshes and
  retries automatically. Persistent 401s → check DevPod broker reachability.
- **429s** — the client backs off and retries; persistent 429s mean you're at
  the 15 RPS consumption-plan ceiling — reduce chat concurrency.
- **Slow answers** — a multi-hop tool loop stacks several model calls and can
  exceed the 45s single-call P95 SLO; expected in v1 (streaming UI is the
  planned mitigation).
- **TLS errors** — set `AIAAS_CA_BUNDLE`/`SCENARIO_API_CA_BUNDLE` to the
  internal CA; do not disable verification (an AST-level test enforces this).
- **RAG returns nothing** — check chunk counts (§7.5a), then ACL groups
  (§7.4): a chunk with empty or mismatched `acl_groups` is invisible to
  everyone.

## 10. Tests (feature-by-feature map)

```bash
.venv/bin/python -m pytest -q                          # everything
.venv/bin/python -m pytest tests/test_tools.py -q      # tool contracts + ACL + citations
.venv/bin/python -m pytest tests/test_orchestrator.py -q  # tool loop, sessions, guardrails
.venv/bin/python -m pytest tests/test_llm_client.py -q    # retries, concurrency, TLS check
.venv/bin/python -m pytest tests/test_ingestion.py -q     # chunking, delta sync, webhooks
.venv/bin/python -m pytest tests/test_registry.py -q      # allowlist behavior
```

Still environment-dependent (run inside the org network, see README):
live AIMart lower-env round trip, and the 15 RPS / 64-concurrency load test.

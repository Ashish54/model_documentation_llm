# Chatbot over the model-docs-wiki knowledge base — options & decision

Goal: let a user chat with the compiled knowledge base (`wiki/concepts/` plus the
typed `wiki/models|methodologies|assumptions|formulas|datasets|validations|limitations/`
layer) in a browser, with citation-traceable answers, and spin it up with
**minimal new requirements**.

What already exists and can be reused (nothing here is rebuilt):

| Asset | What it gives a chatbot for free |
|---|---|
| `llmwiki context "<q>" --json` | Ranked retrieval over the whole wiki (embedding search, or lexical fallback) as machine-readable JSON, incl. source paths / line ranges |
| `llmwiki query "<q>"` | Human-readable ranked results (same engine) |
| `llmwiki serve` | MCP server exposing the wiki to any MCP-capable chat client |
| `llmwiki view --open` | Existing browser UI: search, graph, citations (not conversational) |
| `.env` provider config | Company-hosted Qwen, OpenAI-compatible (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LLMWIKI_MODEL`) — the same endpoint can generate chat answers |
| `[page N]` markers in sources | Citations that map wiki pages back to original PDF pages |

The knowledge base does not need to exist yet for this design: every option
below targets the documented llmwiki surfaces, so the chatbot works as soon as
`llmwiki compile` has produced `wiki/`.

---

## Option A — `llmwiki serve` (MCP) + an existing chat client

Run the wiki's MCP server and point an MCP-capable client (Claude Desktop,
VS Code Copilot, Cursor, …) at it.

- **Effort:** zero new code; one command per user machine.
- **Pros:** lightest possible; retrieval, citations and graph handled by llmwiki; client supplies the chat UX.
- **Cons:** every user needs an MCP client installed and configured; the answering model is whatever the client uses (not necessarily the company Qwen endpoint); UX/governance varies per client; not something you hand to a non-technical stakeholder.
- **Verdict:** great for developers on this repo, not "a chatbot" for general users.

## Option B — Tiny zero-dependency Node chat server (RAG-lite)

A single `.mjs` server (Node built-ins only: `node:http`, `node:child_process`,
`fetch`) plus one static HTML page:

```text
browser (static chat.html)
   │  POST /api/chat { message, history }
   ▼
tools/chat-server.mjs          (node:http, zero npm deps)
   ├── 1. retrieve:  llmwiki context "<message>" --json   (subprocess, timeout)
   ├── 2. prompt:    system rules + ranked pages + last N turns
   ├── 3. generate:  fetch ${OPENAI_BASE_URL}/chat/completions (LLMWIKI_MODEL)
   └── 4. respond:   { answer, sources: [{ title, path, pageRefs }] }
   ▼
chat.html renders the answer with expandable, click-through citations
```

- **Effort:** ~2 small files; no `npm install` of anything new; runs with `node --env-file=.env tools/chat-server.mjs` (Node ≥ 20.6 reads `.env` natively).
- **Pros:** minimal deps and infra (one process, localhost); reuses llmwiki retrieval and ranking verbatim — embeddings *and* the lexical fallback both keep working; API key stays server-side; same Qwen endpoint as the compiler, so no new credentials; citations rendered from real context JSON; fits repo conventions (ESM tools in `tools/`, single dependency policy).
- **Cons:** you maintain a small UI; subprocess-per-query costs a moment of index load (fine at pilot scale); no auth (bind localhost / put behind company proxy if shared).
- **Verdict:** best weight-to-value ratio. **Chosen — see design below.**

## Option C — Python quick-UI (Gradio / Chainlit / Streamlit)

~60 lines of Python: chat widget + subprocess to `llmwiki context` + OpenAI client.

- **Pros:** fastest polished chat UI; streaming/markdown built in.
- **Cons:** introduces a whole second toolchain (Python, venv, pip deps) into a Node repo; another runtime to keep aligned; UI customization is limited; deployment story (port, proxying) is the same as B but with more moving parts.
- **Verdict:** fine if the team is Python-first; otherwise strictly heavier than B for the same result.

## Option D — Static SPA with build-time search index, browser calls the LLM

Export the wiki (+ embeddings) to a JSON index at compile time; a fully static
page does retrieval in-browser and calls the Qwen gateway directly.

- **Pros:** no server process at all; host anywhere.
- **Cons:** `OPENAI_API_KEY` would have to ship to the browser (or you build a proxy — which is a server again, i.e. Option B with extra steps); retrieval/ranking must be reimplemented client-side; index payload can be large; every compile needs a re-export step.
- **Verdict:** rejected — the "no server" saving is paid for with a security hole and duplicated retrieval logic.

## Option E — Full RAG stack (LangChain/LlamaIndex + Chroma/Qdrant + app framework)

- **Pros:** maximal control, ecosystem plugins.
- **Cons:** re-implements what llmwiki already does (chunking, indexing, ranking, citations); adds a vector DB service to run and back up; heavy dependency tree; slowest to spin up; second index to keep in sync with `wiki/`.
- **Verdict:** rejected for this pilot — disproportionate to the need.

## Option F — Slack/Teams bot

- **Pros:** meets users where they are.
- **Cons:** app registration, admin approval, public endpoint/tunnel, secret management, org IT involvement — the opposite of "spun up with minimal requirements".
- **Verdict:** defer; the Option B server can later grow a Slack adapter since retrieval+generation are already factored out.

---

## Decision: Python stdlib server with a sanctioned LLM adapter

Because this environment cannot call the model through an API key, the
implementation is now Python rather than Node. It uses only the Python
standard library plus the already-approved model package. The package-specific
call is isolated behind one configured module/function, so no guessed vendor
import is committed.

Implementation:

- [`tools/chat_server.py`](../tools/chat_server.py) serves the API and invokes
  `llmwiki context "<query>" --json` for retrieval.
- [`tools/chat.html`](../tools/chat.html) is the browser UI.
- Set `CHAT_LLM_MODULE` to an importable local adapter module and optionally
  `CHAT_LLM_FUNCTION` (default: `generate`). The callable receives
  `list[{"role": "...", "content": "..."}]` and returns text. A synchronous or
  asynchronous callable is supported.

Example adapter shape (implemented in your environment, not this repository):

```python
def generate(messages):
    return sanctioned_package_client.chat(messages=messages)
```

Run after the KB has been compiled:

```bash
CHAT_LLM_MODULE=my_company_llm_adapter \
  PYTHONPATH=/path/to/your/adapter:$PYTHONPATH \
  python tools/chat_server.py
# open http://127.0.0.1:8787
```

The server binds to loopback, keeps credentials inside the sanctioned package,
limits request/history/context sizes, and is read-only with respect to the
typed model-docs layer.

### Why this is now the best option

It avoids both an API-key HTTP call and a Node-to-Python bridge. Retrieval
continues to use llmwiki's existing ranking, embeddings, lexical fallback, and
citations. There is no vector database, web framework, frontend build, or
second retrieval implementation to operate.

## Earlier decision: Option B — zero-dep Node RAG-lite server

The original Node option was chosen because it was simultaneously: (1) zero new npm
dependencies, (2) one process to start, (3) no duplicated retrieval logic
(it *is* `llmwiki context`), (4) server-side credentials, and (5) a real chat
UX you can hand to anyone with a browser. Option A remains available as a
zero-code path for developers. It is superseded by the Python implementation
above because model generation must occur through the sanctioned Python package.

### Architecture & request flow

```text
┌────────────────────────────┐
│ tools/chat-ui.html         │  static page: message list, input box,
│ (served at GET /)          │  sends {message, history(last 6 turns)}
└─────────────┬──────────────┘
              │ POST /api/chat
┌─────────────▼──────────────┐
│ tools/chat-server.mjs      │
│ 1. retrieve  ── execFile: llmwiki context "<message>" --json
│                (60s timeout, 4 MB stdout cap)
│ 2. assemble  ── system prompt + ≤ CONTEXT_BUDGET chars of ranked pages
│                (each page labelled with title + source path) + history
│ 3. generate  ── POST ${OPENAI_BASE_URL}/chat/completions
│                model = LLMWIKI_MODEL, temperature ≈ 0.2
│ 4. respond   ── { answer, sources[] }  (sources = pages used, with
│                source path + [page N] refs for citation rendering)
└────────────────────────────┘
```

Stateless server: conversation history lives in the browser and is resent
(truncated to the last few turns) with each request. No database, no sessions.

### Files

| File | Purpose |
|---|---|
| `tools/chat_server.py` | HTTP server, retrieval subprocess, adapter-backed generation |
| `tools/chat.html` | Single-page vanilla JavaScript chat UI |

### Configuration (reuses existing `.env`)

| Variable | Default | Notes |
|---|---|---|
| `CHAT_LLM_MODULE` | — | importable adapter module for the sanctioned Python package |
| `CHAT_LLM_FUNCTION` | `generate` | callable in that module |
| `CHAT_PORT` | `8787` | binds `127.0.0.1` by default |
| `CHAT_CONTEXT_CHARS` | `60000` | cap on retrieved context stuffed into the prompt (mirrors the runbook's prompt-budget guidance) |
| `CHAT_HISTORY_TURNS` | `6` | how much client-sent history is included |
| `LLMWIKI_BIN` | `llmwiki` | path to the CLI (same alias as the runbook uses) |

Run: `python tools/chat_server.py` → open `http://127.0.0.1:8787`.

### Prompting & guardrails

- System prompt: answer **only** from the supplied context; cite claims with
  the page title and `[page N]` markers; if the context doesn't contain the
  answer, say the knowledge base doesn't cover it and suggest a rephrased query.
- Low temperature (≈0.2) to keep answers grounded.
- The bot is **read-only by design** — it never touches typed-write surfaces,
  so the profile's lifecycle gates and `LLMWIKI_TRUSTED_WRITE` trust model are
  unaffected.

### Failure modes (all answered in-chat, never a bare stack trace)

| Failure | Behaviour |
|---|---|
| `wiki/` absent / empty (KB not compiled yet) | retrieval returns nothing → bot replies "knowledge base is empty, run llmwiki compile" |
| `llmwiki` binary missing | startup check + clear error naming `LLMWIKI_BIN` |
| retrieval subprocess timeout/non-zero | bot apologises, suggests retry; error logged server-side |
| LLM endpoint down/timeout | friendly message; `LLMWIKI_REQUEST_TIMEOUT_MS` honoured |
| no embedding endpoint | nothing to do — llmwiki's lexical fallback keeps retrieval working (per `.env.example`) |

### Known limits & upgrade path (only if usage grows)

1. **Subprocess per query** reloads the index (~1–2 s). Fix: hold one persistent
   `llmwiki serve` MCP stdio session and call its context tool instead.
2. **Follow-up questions** ("what about *its* assumptions?") retrieve poorly
   because the query lacks context. Fix: one extra cheap LLM call to rewrite the
   follow-up into a standalone query before retrieval.
3. **Streaming answers** (SSE) — nicety, not needed for pilot.
4. **Sharing beyond localhost** — put the server behind the company SSO/reverse
   proxy rather than adding auth code.
5. **Multi-turn memory** beyond N turns, conversation persistence, feedback
   buttons — defer.

### Why not just ship Option A?

For developers on this repo, do both: `llmwiki serve` remains the zero-code
path. But the deliverable asked for is a chatbot for *users of the knowledge
base* — Option B is the lightest thing that is a self-contained, send-a-link
chatbot with governed answers from the company endpoint and clickable
`[page N]` citations back to the source PDFs.

"""FastAPI chat service for the v1 internal web UI (plan Step 9).

Exposes the orchestrator over HTTP. Auth: Entra ID SSO bearer token; the
token's claims are decoded into a ToolContext (user id + group claims for the
OBO calls and the pgvector ACL filter — §3.5). The claims decoder is
injectable; wire the tenant's JWKS validation in deployment.

Run: uvicorn 'api:create_app' --factory  (after configuring env vars below)

Note: no `from __future__ import annotations` here — FastAPI must resolve the
endpoint annotations (incl. the request models) eagerly at decoration time.
"""

import os
import uuid
from typing import Mapping, Optional, Protocol

from llm_client import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GATEWAY_BASE_URL,
    LLMClient,
    make_devpod_token_provider,
)
from orchestrator import Orchestrator
from tool_registry import ToolRegistry
from tools.base import ToolContext


class ClaimsDecoder(Protocol):
    def decode(self, token: str) -> Mapping: ...


def build_orchestrator(
    *,
    llm: Optional[LLMClient] = None,
    scenario_api=None,
    compare_fn=None,
    embedder=None,
    store=None,
) -> Orchestrator:
    """Composition root: static in-code registry built at startup (§3.6)."""
    from tools import (
        CompareScenariosTool,
        GetScenarioDataTool,
        ListScenariosTool,
        SearchKnowledgeBaseTool,
    )

    if llm is None:
        llm = LLMClient(
            token_provider=make_devpod_token_provider(),
            base_url=os.environ.get("AIAAS_GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
            ca_bundle=os.environ.get("AIAAS_CA_BUNDLE"),
        )
    if scenario_api is None:
        from tools.scenario_api import HttpScenarioAPIClient

        scenario_api = HttpScenarioAPIClient(
            os.environ["SCENARIO_API_BASE_URL"],
            ca_bundle=os.environ.get("SCENARIO_API_CA_BUNDLE"),
        )
    if embedder is None or store is None:
        from ingestion.embedder import Embedder
        from vector_store import PgVectorStore

        embedder = Embedder(llm, model=DEFAULT_EMBEDDING_MODEL)
        store = PgVectorStore(os.environ["PGVECTOR_DSN"])

    registry = ToolRegistry(
        [
            ListScenariosTool(scenario_api),
            GetScenarioDataTool(scenario_api),
            CompareScenariosTool(compare_fn),
            SearchKnowledgeBaseTool(embedder, store),
        ]
    )
    return Orchestrator(llm, registry, chat_model=DEFAULT_CHAT_MODEL)


def create_app(
    orchestrator: Optional[Orchestrator] = None,
    claims_decoder: Optional[ClaimsDecoder] = None,
):
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel

    class ChatRequest(BaseModel):
        session_id: Optional[str] = None
        message: str

    class ChatResponseBody(BaseModel):
        session_id: str
        answer: str

    if orchestrator is None:
        orchestrator = build_orchestrator()

    app = FastAPI(title="Scenario Comparison Chatbot")

    async def current_context(
        authorization: str = Header(...),
    ) -> ToolContext:
        token = authorization.removeprefix("Bearer ").strip()
        if claims_decoder is None:
            raise HTTPException(503, "token validation not configured")
        try:
            claims = claims_decoder.decode(token)
        except Exception:
            raise HTTPException(401, "invalid token") from None
        return ToolContext(
            user_id=str(claims.get("oid") or claims.get("sub") or "unknown"),
            group_claims=frozenset(claims.get("groups") or ()),
            correlation_id=uuid.uuid4().hex,
            obo_token=token,  # exchanged downstream for scenario APIs (OBO)
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponseBody)
    async def chat(
        request: ChatRequest, context: ToolContext = Depends(current_context)
    ) -> ChatResponseBody:
        session_id = request.session_id or orchestrator.new_session()
        answer = await orchestrator.handle_message(
            session_id, request.message, context
        )
        return ChatResponseBody(session_id=session_id, answer=answer)

    return app


# Serve with: uvicorn 'api:create_app' --factory
# (env: AIAAS_GATEWAY_BASE_URL, AIAAS_CA_BUNDLE, SCENARIO_API_BASE_URL, PGVECTOR_DSN)

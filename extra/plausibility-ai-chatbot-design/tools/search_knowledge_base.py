"""`search_knowledge_base` tool — RAG over the SharePoint grounding index.

The query is normalized and embedded with the `query:` prefix (matching the
`document:` prefix used at ingestion), then matched against pgvector with the
ACL security filter applied from the caller's Entra group claims (§3.4).
Results carry citations so every KB-grounded answer is traceable (§3.4.5).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from tools.base import Tool, ToolContext, ToolResult, validate_args
from vector_store import VectorStore


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> list[float]:
        """Normalize + `query:`-prefix + embed one search query."""
        ...


class SearchKnowledgeBaseTool(Tool):
    name = "search_knowledge_base"
    version = "1.0.0"
    description = (
        "Search the economist knowledge base (SharePoint grounding content: "
        "definitions, methodology, assumptions) for passages relevant to a "
        "query. Use only for grounding/explanation — never as a source of "
        "scenario numbers. Results include citations (title + SharePoint "
        "link) that must be shown to the user."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max passages to return (default 5, max 20).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    MAX_TOP_K = 20
    DEFAULT_TOP_K = 5

    def __init__(self, embedder: QueryEmbedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    async def call(self, args: Mapping[str, Any], context: ToolContext) -> ToolResult:
        if error := validate_args(self.args_schema, args):
            return ToolResult.failure(error)
        top_k = args.get("top_k", self.DEFAULT_TOP_K)
        if not 1 <= top_k <= self.MAX_TOP_K:
            return ToolResult.failure(f"top_k must be between 1 and {self.MAX_TOP_K}")
        try:
            embedding = await self._embedder.embed_query(args["query"])
            chunks = await self._store.similarity_search(
                embedding,
                acl_groups=context.group_claims,
                top_k=top_k,
            )
        except Exception:
            return ToolResult.failure("knowledge base unavailable")
        return ToolResult.ok(
            {
                "passages": [
                    {
                        "content": c.content,
                        "score": round(c.score, 6),
                        "citation": c.citation(),
                        "site": c.site,
                        "author": c.author,
                        "modified_at": c.modified_at,
                        "doc_version": c.doc_version,
                    }
                    for c in chunks
                ]
            }
        )

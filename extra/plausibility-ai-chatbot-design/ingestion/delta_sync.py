"""Graph delta-sync ingestion worker (ARCHITECTURE §3.4).

The delta query is the source of truth for what changed; webhooks are only a
latency optimization. Each run resumes from the stored delta token per site,
so the sync is idempotent and self-healing after missed webhook events.

Pipeline per changed item: download → parse → chunk (within the 8,192-token
embedding input limit) → embed with the `document:` prefix → upsert into
pgvector by stable key (doc_id + chunk_index). Deleted items remove their
chunks by the same key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence

from ingestion.embedder import Embedder, chunk_text
from vector_store import Chunk, VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DriveItem:
    """A changed SharePoint drive item from the Graph delta feed."""

    item_id: str
    name: str
    web_url: str
    site: str
    deleted: bool = False
    content: Optional[bytes] = None  # downloaded file bytes (new/updated)
    modified_at: Optional[str] = None
    author: Optional[str] = None
    doc_version: Optional[str] = None
    acl_groups: frozenset[str] = frozenset()  # resolved via /items/{id}/permissions


class GraphDeltaClient(Protocol):
    async def delta(
        self, site_id: str, delta_token: Optional[str]
    ) -> tuple[Sequence[DriveItem], Optional[str]]:
        """Return (changed items, next delta token)."""
        ...


class Parser(Protocol):
    def parse(self, content: bytes, *, name: str) -> str:
        """Extract plain text from a downloaded file (PDF/Office/etc.)."""
        ...


class StateStore(Protocol):
    async def get_delta_token(self, site_id: str) -> Optional[str]: ...
    async def set_delta_token(self, site_id: str, token: Optional[str]) -> None: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self._tokens: dict[str, Optional[str]] = {}

    async def get_delta_token(self, site_id: str) -> Optional[str]:
        return self._tokens.get(site_id)

    async def set_delta_token(self, site_id: str, token: Optional[str]) -> None:
        self._tokens[site_id] = token


class DeltaSync:
    def __init__(
        self,
        graph: GraphDeltaClient,
        parser: Parser,
        embedder: Embedder,
        store: VectorStore,
        state: StateStore,
        *,
        max_chunk_tokens: int | None = None,
    ) -> None:
        self._graph = graph
        self._parser = parser
        self._embedder = embedder
        self._store = store
        self._state = state
        self._max_chunk_tokens = max_chunk_tokens

    async def run_once(self, site_id: str) -> Mapping[str, int]:
        token = await self._state.get_delta_token(site_id)
        items, next_token = await self._graph.delta(site_id, token)
        stats = {"upserted_docs": 0, "deleted_docs": 0, "chunks": 0}

        for item in items:
            if item.deleted:
                await self._store.delete_document(item.item_id)
                stats["deleted_docs"] += 1
                continue
            if item.content is None:
                logger.warning("delta item %s has no content; skipping", item.item_id)
                continue
            text = self._parser.parse(item.content, name=item.name)
            chunk_kwargs: dict[str, Any] = {}
            if self._max_chunk_tokens is not None:
                chunk_kwargs["max_chunk_tokens"] = self._max_chunk_tokens
            pieces = chunk_text(text, **chunk_kwargs)
            if not pieces:
                continue
            embeddings = await self._embedder.embed_documents(pieces)
            chunks = [
                Chunk(
                    doc_id=item.item_id,
                    chunk_index=i,
                    content=piece,
                    title=item.name,
                    source_url=item.web_url,
                    site=item.site,
                    author=item.author,
                    modified_at=item.modified_at,
                    doc_version=item.doc_version,
                    acl_groups=item.acl_groups,
                )
                for i, piece in enumerate(pieces)
            ]
            await self._store.upsert_chunks(chunks, embeddings)
            stats["upserted_docs"] += 1
            stats["chunks"] += len(chunks)

        await self._state.set_delta_token(site_id, next_token)
        logger.info("delta_sync site=%s stats=%s", site_id, dict(stats))
        return stats

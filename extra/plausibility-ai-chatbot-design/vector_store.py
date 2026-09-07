"""Vector store seam for the pgvector-backed grounding index (ARCHITECTURE §3.3).

``VectorStore`` is the protocol the RAG tool and ingestion worker depend on.
``PgVectorStore`` is the production implementation (local pgvector, ACL
security filter applied in SQL). ``InMemoryVectorStore`` implements the same
contract for tests and local development.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

EMBEDDING_DIMENSION = 1024  # Matryoshka default, fixed for v1


@dataclass(frozen=True)
class Chunk:
    """One indexed KB chunk with citation + ACL metadata (§3.3/§3.4)."""

    doc_id: str  # SharePoint item ID (stable key part)
    chunk_index: int  # stable key part
    content: str
    title: str
    source_url: str
    site: str
    author: Optional[str] = None
    modified_at: Optional[str] = None
    doc_version: Optional[str] = None
    acl_groups: frozenset[str] = frozenset()
    score: float = 0.0

    def citation(self) -> dict[str, str]:
        return {"title": self.title, "source_url": self.source_url}


class VectorStore(Protocol):
    async def upsert_chunks(
        self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        """Insert or replace chunks keyed by (doc_id, chunk_index)."""
        ...

    async def delete_document(self, doc_id: str) -> None:
        """Remove all chunks of a deleted/moved SharePoint item."""
        ...

    async def similarity_search(
        self,
        embedding: Sequence[float],
        *,
        acl_groups: frozenset[str],
        top_k: int,
    ) -> list[Chunk]:
        """Cosine-similarity search with the ACL security filter applied:
        only chunks whose acl_groups intersect the caller's Entra group
        claims are eligible (§3.4)."""
        ...


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryVectorStore:
    """Reference implementation of the VectorStore contract (tests/dev)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], tuple[Chunk, list[float]]] = {}

    async def upsert_chunks(
        self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")
        for chunk, embedding in zip(chunks, embeddings):
            if len(embedding) != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"embedding dimension {len(embedding)} != {EMBEDDING_DIMENSION}"
                )
            self._rows[(chunk.doc_id, chunk.chunk_index)] = (chunk, list(embedding))

    async def delete_document(self, doc_id: str) -> None:
        for key in [k for k in self._rows if k[0] == doc_id]:
            del self._rows[key]

    async def similarity_search(
        self,
        embedding: Sequence[float],
        *,
        acl_groups: frozenset[str],
        top_k: int,
    ) -> list[Chunk]:
        visible = [
            (chunk, vec)
            for chunk, vec in self._rows.values()
            if chunk.acl_groups & acl_groups
        ]
        scored = sorted(
            visible, key=lambda cv: _cosine(embedding, cv[1]), reverse=True
        )[:top_k]
        return [
            Chunk(
                doc_id=c.doc_id,
                chunk_index=c.chunk_index,
                content=c.content,
                title=c.title,
                source_url=c.source_url,
                site=c.site,
                author=c.author,
                modified_at=c.modified_at,
                doc_version=c.doc_version,
                acl_groups=c.acl_groups,
                score=_cosine(embedding, vec),
            )
            for c, vec in scored
        ]


class PgVectorStore:
    """Production store against local pgvector (schema: db/pgvector_schema.sql).

    Uses asyncpg (imported lazily). The ACL security filter is applied in SQL:
    ``acl_groups && $2`` restricts to chunks sharing at least one group with
    the caller's Entra claims (§3.4 token-based row-level security).
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg  # type: ignore[import-not-found]

            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool

    async def upsert_chunks(
        self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO kb_chunks (
                    doc_id, chunk_index, content, title, source_url, site,
                    author, modified_at, doc_version, acl_groups, embedding
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (doc_id, chunk_index) DO UPDATE SET
                    content = EXCLUDED.content,
                    title = EXCLUDED.title,
                    source_url = EXCLUDED.source_url,
                    site = EXCLUDED.site,
                    author = EXCLUDED.author,
                    modified_at = EXCLUDED.modified_at,
                    doc_version = EXCLUDED.doc_version,
                    acl_groups = EXCLUDED.acl_groups,
                    embedding = EXCLUDED.embedding
                """,
                [
                    (
                        c.doc_id,
                        c.chunk_index,
                        c.content,
                        c.title,
                        c.source_url,
                        c.site,
                        c.author,
                        c.modified_at,
                        c.doc_version,
                        sorted(c.acl_groups),
                        list(e),
                    )
                    for c, e in zip(chunks, embeddings)
                ],
            )

    async def delete_document(self, doc_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM kb_chunks WHERE doc_id = $1", doc_id)

    async def similarity_search(
        self,
        embedding: Sequence[float],
        *,
        acl_groups: frozenset[str],
        top_k: int,
    ) -> list[Chunk]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT doc_id, chunk_index, content, title, source_url, site,
                       author, modified_at, doc_version, acl_groups,
                       1 - (embedding <=> $1::vector) AS score
                FROM kb_chunks
                WHERE acl_groups && $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                list(embedding),
                sorted(acl_groups),
                top_k,
            )
        return [
            Chunk(
                doc_id=r["doc_id"],
                chunk_index=r["chunk_index"],
                content=r["content"],
                title=r["title"],
                source_url=r["source_url"],
                site=r["site"],
                author=r["author"],
                modified_at=str(r["modified_at"]) if r["modified_at"] else None,
                doc_version=r["doc_version"],
                acl_groups=frozenset(r["acl_groups"]),
                score=float(r["score"]),
            )
            for r in rows
        ]

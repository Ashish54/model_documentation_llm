"""Chunking + embedding for the ingestion pipeline and runtime search.

Rules (ARCHITECTURE §3.3, Qwen3-Embedding-8B handover):
  * The embedding model's context window is 8,192 tokens — every chunk must
    fit, with headroom reserved for the `document:` prefix.
  * Embedding dimension is fixed at 1024 for v1 (enforced by the store).
  * Text normalization (NFC, whitespace collapse) is applied identically at
    ingestion and at query time, and `document:` / `query:` prefixes keep
    both sides in the same embedding space.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol, Sequence

EMBEDDING_MAX_TOKENS = 8192
# Conservative chars-per-token estimate plus safety margin so no chunk risks
# exceeding the model's 8,192-token input limit.
CHARS_PER_TOKEN_ESTIMATE = 4
SAFETY_MARGIN = 0.9
DEFAULT_MAX_CHUNK_TOKENS = 1024  # well under the model limit; tune after first ingestion test

DOCUMENT_PREFIX = "document: "
QUERY_PREFIX = "query: "


def normalize_text(text: str) -> str:
    """Consistent normalization for indexing and querying."""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE + 1)


def chunk_text(
    text: str,
    *,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
    prefix: str = DOCUMENT_PREFIX,
) -> list[str]:
    """Split normalized text into chunks that fit the embedding input limit.

    Splits on paragraph boundaries first, then hard-splits over-long
    paragraphs. ``max_chunk_tokens`` is capped so chunk + prefix stays within
    the model's 8,192-token window.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []
    budget_tokens = min(
        max_chunk_tokens,
        int((EMBEDDING_MAX_TOKENS - _estimate_tokens(prefix)) * SAFETY_MARGIN),
    )
    max_chars = budget_tokens * CHARS_PER_TOKEN_ESTIMATE

    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        paragraph = normalize_text(paragraph)
        if not paragraph:
            continue
        while len(paragraph) > max_chars:
            head, paragraph = paragraph[:max_chars], paragraph[max_chars:]
            chunks.append(head if not current else current + " " + head)
            current = ""
        candidate = f"{current} {paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class EmbeddingClient(Protocol):
    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        ...


class Embedder:
    """Embeds documents (ingestion) and queries (runtime search) consistently."""

    def __init__(self, client: EmbeddingClient, model: str) -> None:
        self._client = client
        self._model = model

    async def embed_documents(self, chunks: Sequence[str]) -> list[list[float]]:
        prefixed = [DOCUMENT_PREFIX + normalize_text(c) for c in chunks]
        return await self._client.embed(prefixed, model=self._model)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._client.embed(
            [QUERY_PREFIX + normalize_text(text)], model=self._model
        )
        return vectors[0]

"""Ingestion pipeline tests: chunking within the embedding model's 8,192-token
input limit, `document:` prefixing, delta-sync upsert/delete by stable key,
and webhook handling."""

from ingestion.delta_sync import (
    DeltaSync,
    DriveItem,
    InMemoryStateStore,
)
from ingestion.embedder import (
    CHARS_PER_TOKEN_ESTIMATE,
    DOCUMENT_PREFIX,
    EMBEDDING_MAX_TOKENS,
    Embedder,
    chunk_text,
    normalize_text,
)
from ingestion.webhook_handler import WebhookHandler, parse_site_id
from vector_store import InMemoryVectorStore


class FakeEmbeddingClient:
    def __init__(self):
        self.calls = []

    async def embed(self, texts, *, model):
        self.calls.append((list(texts), model))
        return [[1.0] + [0.0] * 1023 for _ in texts]


def make_embedder():
    return Embedder(FakeEmbeddingClient(), model="Qwen/Qwen3-Embedding-8B")


# --- chunking ---

def test_chunks_fit_embedding_input_limit():
    text = "word " * 20000  # ~100KB of text
    chunks = chunk_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        prefixed = DOCUMENT_PREFIX + chunk
        estimated_tokens = len(prefixed) / CHARS_PER_TOKEN_ESTIMATE
        assert estimated_tokens <= EMBEDDING_MAX_TOKENS


def test_chunk_text_empty_and_normalization():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []
    assert normalize_text("a\t b\n\n  c") == "a b c"


def test_chunk_text_preserves_all_content():
    paragraphs = [f"paragraph {i} " + ("x " * 50) for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_chunk_tokens=100)
    rejoined = " ".join(chunks)
    for i in range(10):
        assert f"paragraph {i}" in rejoined


# --- embedder prefixes ---

async def test_embedder_uses_document_prefix_and_normalizes():
    client = FakeEmbeddingClient()
    embedder = Embedder(client, model="m")
    await embedder.embed_documents(["  Some   Text "])
    assert client.calls[0][0] == ["document: Some Text"]


async def test_embedder_query_prefix():
    embedder = make_embedder()
    vector = await embedder.embed_query("gdp")
    assert len(vector) == 1024


# --- delta sync ---

class FakeGraph:
    def __init__(self, items, next_token="tok-2"):
        self._items = items
        self._next_token = next_token
        self.calls = []

    async def delta(self, site_id, delta_token):
        self.calls.append((site_id, delta_token))
        return self._items, self._next_token


class FakeParser:
    def parse(self, content, *, name):
        return content.decode()


async def test_delta_sync_upserts_new_items_with_metadata():
    item = DriveItem(
        item_id="item-1",
        name="Methodology.pdf",
        web_url="https://sp/Methodology.pdf",
        site="economics",
        content=b"GDP methodology assumptions",
        modified_at="2026-01-01",
        author="econ@corp",
        doc_version="3",
        acl_groups=frozenset({"grp-economists"}),
    )
    graph = FakeGraph([item])
    store = InMemoryVectorStore()
    state = InMemoryStateStore()
    sync = DeltaSync(graph, FakeParser(), make_embedder(), store, state)

    stats = await sync.run_once("site-1")

    assert stats == {"upserted_docs": 1, "deleted_docs": 0, "chunks": 1}
    results = await store.similarity_search(
        [1.0] + [0.0] * 1023, acl_groups=frozenset({"grp-economists"}), top_k=5
    )
    assert len(results) == 1
    chunk = results[0]
    assert chunk.doc_id == "item-1"
    assert chunk.title == "Methodology.pdf"
    assert chunk.source_url == "https://sp/Methodology.pdf"
    assert chunk.acl_groups == frozenset({"grp-economists"})
    # Resumable state: next run continues from the new delta token.
    assert await state.get_delta_token("site-1") == "tok-2"


async def test_delta_sync_resumes_from_stored_token():
    graph = FakeGraph([], next_token="tok-3")
    state = InMemoryStateStore()
    await state.set_delta_token("site-1", "tok-2")
    sync = DeltaSync(graph, FakeParser(), make_embedder(), InMemoryVectorStore(), state)
    await sync.run_once("site-1")
    assert graph.calls == [("site-1", "tok-2")]
    assert await state.get_delta_token("site-1") == "tok-3"


async def test_delta_sync_deleted_item_removes_chunks():
    store = InMemoryVectorStore()
    from vector_store import Chunk

    await store.upsert_chunks(
        [Chunk(doc_id="item-1", chunk_index=0, content="c", title="t",
               source_url="u", site="s", acl_groups=frozenset({"g"}))],
        [[1.0] + [0.0] * 1023],
    )
    deleted = DriveItem(
        item_id="item-1", name="t", web_url="u", site="s", deleted=True
    )
    sync = DeltaSync(
        FakeGraph([deleted]), FakeParser(), make_embedder(), store, InMemoryStateStore()
    )
    stats = await sync.run_once("site-1")
    assert stats["deleted_docs"] == 1
    results = await store.similarity_search(
        [1.0] + [0.0] * 1023, acl_groups=frozenset({"g"}), top_k=5
    )
    assert results == []


# --- webhook handler ---

def test_parse_site_id():
    assert parse_site_id("/sites/site-42/drive/root") == "site-42"


def test_webhook_validation_handshake_echoes_token():
    handler = WebhookHandler(lambda site: _noop())
    status, body = handler.handle_validation("validation-token-123")
    assert status == 200
    assert body == "validation-token-123"


async def _noop(site=None):
    return None


async def test_webhook_notification_triggers_delta_sync_per_site():
    triggered = []

    async def trigger(site_id):
        triggered.append(site_id)

    handler = WebhookHandler(trigger, validation_token="secret")
    result = await handler.handle_notification(
        {
            "value": [
                {"resource": "/sites/site-42/drive/root", "clientState": "secret"},
                {"resource": "/sites/site-99/drive/root", "clientState": "wrong"},
            ]
        }
    )
    # Only the correctly-authenticated notification triggers a sync.
    assert triggered == ["site-42"]
    assert result["accepted"] == 1

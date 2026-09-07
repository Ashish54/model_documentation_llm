-- pgvector schema for the SharePoint grounding index (ARCHITECTURE §3.3).
-- Local pgvector store; embedding dimension fixed at 1024 for v1
-- (Qwen/Qwen3-Embedding-8B Matryoshka default — change requires re-embedding).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_chunks (
    id           BIGSERIAL PRIMARY KEY,
    -- Stable key: SharePoint item ID + chunk index (used for upsert/delete).
    doc_id       TEXT        NOT NULL,
    chunk_index  INTEGER     NOT NULL,
    content      TEXT        NOT NULL,
    -- Citation / traceability metadata (§3.3).
    title        TEXT        NOT NULL,
    source_url   TEXT        NOT NULL,
    site         TEXT        NOT NULL,
    library      TEXT,
    author       TEXT,
    modified_at  TIMESTAMPTZ,
    doc_version  TEXT,
    -- ACL security filter: resolved Entra group IDs allowed to see the
    -- source document (§3.4). Query side: WHERE acl_groups && :user_groups.
    acl_groups   TEXT[]      NOT NULL DEFAULT '{}',
    embedding    vector(1024) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunk_index)
);

-- Approximate nearest-neighbour search (cosine distance).
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw
    ON kb_chunks USING hnsw (embedding vector_cosine_ops);

-- Fast ACL security-filter lookups.
CREATE INDEX IF NOT EXISTS kb_chunks_acl_gin
    ON kb_chunks USING GIN (acl_groups);

-- Delta-sync bookkeeping: last Graph delta token per site.
CREATE TABLE IF NOT EXISTS ingestion_state (
    site_id     TEXT PRIMARY KEY,
    delta_token TEXT,
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

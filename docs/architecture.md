# Architecture — modelkb

Concise system shape. Rationale lives in `adrs/` (0001 versioning,
0002 graph/conflicts, 0003 two-pass schema, 0004 LLM audit, 0005 DB
portability).

## Context

```mermaid
flowchart LR
    subgraph Sources
        SP[SharePoint folder<br/>today: local mirror]
        MI[model_info.json]
        GIT[Python model library<br/>one configured Git tag]
    end
    subgraph Pipeline["modelkb pipeline (Python)"]
        A[Pass A: deterministic<br/>discovery + parse]
        S[Schema proposal<br/>vLLM, audited]
        B[Pass B: schema-guided<br/>semantic extraction]
        C[Code inventory<br/>AST only]
    end
    subgraph Stores
        AR[(Immutable archive<br/>sha256-addressed PDFs)]
        DB[(PostgreSQL<br/>31 tables + evidence graph)]
        KN[(Knowledge artifacts<br/>Markdown + YAML)]
    end
    LLM[(Regional vLLM endpoint<br/>chat-only today)]
    SP --> A --> S --> B
    MI --> B
    GIT --> C
    A --> AR
    S <-->|structured JSON| LLM
    B <-->|structured JSON| LLM
    B --> DB
    C --> DB
    DB --> KN
```

## Pass A flow (implemented, milestones 1–3)

```mermaid
sequenceDiagram
    participant CLI as kb discover-corpus
    participant SRC as LocalFolderSource
    participant AR as ArtifactStore
    participant P as PyMuPdfParser
    participant DB as PostgreSQL/SQLite
    participant LLM as vLLM (chat_only)
    CLI->>SRC: iter candidates (*.pdf)
    loop per document (savepoint-isolated)
        SRC-->>CLI: candidate path
        CLI->>AR: put(bytes) → sha256, read-only copy
        alt content already archived
            AR-->>CLI: skip (idempotent)
        else new content
            CLI->>P: parse → pages, sections, tables, equations, citations, code refs, quality
            CLI->>DB: artifact_version + document_version + page + section + source_locator
        end
    end
    CLI->>DB: discovery report (extractions/discovery/<run>/)
    Note over CLI,LLM: kb propose-schema --discovery-run <id>
    CLI->>LLM: discovery report + versioned prompt
    LLM-->>CLI: SchemaProposal JSON (validated, repaired once)
    CLI->>DB: schema YAML+JSON files + schema_version(proposed) + llm_interaction
```

## Pass B flow (planned, milestones 4–7)

```text
active corpus schema
        │
        ▼
per document: deterministic candidates (tables, equations, metadata)
        │  LLM only for classification / normalization / semantic extraction
        ▼
validated JSON (Pydantic) ── nulls, confidence, reasoning_category,
        │                    evidence IDs required per substantive field
        ▼
claims/assumptions/variables/equations/coefficients + evidence links
        │
        ▼
relationship assertions (PDF precedence 20 > model_info 10)
        │  conflicts retained + marked; deterministic resolver → current view
        ▼
Markdown/YAML knowledge artifacts (frontmatter cites evidence IDs)
```

## Evidence and versioning model

```mermaid
erDiagram
    ARTIFACT ||--o{ ARTIFACT_VERSION : versions
    ARTIFACT_VERSION ||--o{ SOURCE_LOCATOR : "evidence atoms"
    DOCUMENT ||--o{ DOCUMENT_VERSION : revisions
    DOCUMENT_VERSION ||--o{ PAGE : pages
    DOCUMENT_VERSION ||--o{ SECTION : headings
    MODEL ||--o{ MODEL_VERSION : versions
    CLAIM ||--o{ CLAIM_VERSION : versions
    RELATIONSHIP }o--o{ SOURCE_LOCATOR : relationship_evidence
    ASSUMPTION }o--o{ SOURCE_LOCATOR : assumption_evidence
    VARIABLE }o--o{ SOURCE_LOCATOR : variable_evidence
    EQUATION }o--o{ SOURCE_LOCATOR : equation_evidence
```

* Append-only everywhere; `is_current` moves, history stays.
* `recorded_at` (system) vs `valid_from`/`source_modified_at` (source) time.
* Relationship indexes `ix_relationship_forward/reverse` prepare recursive
  PostgreSQL traversal.

## Deployment view

| Environment | Database | LLM backend | Notes |
|---|---|---|---|
| Dev / tests (today) | SQLite file | `chat_only` (JSON emulation) | zero-install; psycopg not required |
| Shared / prod | PostgreSQL (`KB_DATABASE__URL`) | `chat_only` or `direct` (guided JSON) | JSONB + traversal indexes activate |

Auth seam: no API key today; company auth plugs into
`VllmProvider._headers()` only (ADR 0004).

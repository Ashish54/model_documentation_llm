"""Discovery report schemas — the structured output of Pass A.

The report (not raw pages) is what the schema-proposal LLM sees, and it is a
reviewable artifact in its own right: it tells a human whether the corpus is
structurally uniform before anyone commits to an extraction schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    artifact_sha256: str
    source_name: str
    document_ref: str
    document_version_ref: str
    title_candidate: str | None = None
    metadata_candidates: dict[str, Any] = Field(default_factory=dict)
    page_count: int
    has_toc: bool
    headings: list[dict[str, Any]] = Field(default_factory=list)  # [{path, level, page}]
    table_shapes: list[dict[str, Any]] = Field(default_factory=list)  # [{label, n_rows, n_cols}]
    equation_labels: list[str] = Field(default_factory=list)
    citation_count: int = 0
    code_references: list[dict[str, Any]] = Field(default_factory=list)
    relationship_language: list[str] = Field(default_factory=list)  # sampled lines
    extraction_warnings: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)


class CorpusAggregate(BaseModel):
    document_count: int
    documents_with_toc: int
    documents_with_warnings: list[str]
    common_headings: list[dict[str, Any]] = Field(default_factory=list)
    distinct_table_shapes: list[str] = Field(default_factory=list)  # e.g. "2x3"
    equation_label_styles: list[str] = Field(default_factory=list)
    all_code_reference_paths: list[str] = Field(default_factory=list)
    total_pages: int


class DiscoveryReport(BaseModel):
    run_id: str
    input_dir: str
    documents: list[DocumentSummary]
    aggregate: CorpusAggregate

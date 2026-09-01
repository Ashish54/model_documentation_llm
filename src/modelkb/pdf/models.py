"""Pydantic records produced by deterministic PDF parsing.

These double as the on-disk JSON/JSONL schemas of the extraction package
(extractions/<artifact_sha256>/), so disk and database stay in lockstep.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageRecord(BaseModel):
    page_number: int  # 1-based
    text: str
    text_hash: str
    char_count: int
    warnings: list[str] = Field(default_factory=list)


class SectionRecord(BaseModel):
    heading: str
    heading_path: list[str]  # root → leaf, e.g. ["3 Model methodology", "3.2 Rates"]
    level: int
    page_start: int | None
    page_end: int | None
    order_index: int
    detection: str  # toc | numbered | font
    confidence: float = 1.0


class TableRecord(BaseModel):
    table_id: str  # deterministic within the document: p<page>_t<index>
    page: int
    label: str | None = None  # "Table 4" when a caption is found
    bbox: list[float] | None = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    n_rows: int
    n_cols: int


class EquationRecord(BaseModel):
    page: int
    text: str
    label: str | None = None  # "Equation 2" / "(3)"
    bbox: list[float] | None = None


class CitationRecord(BaseModel):
    page: int
    raw: str
    kind: str  # reference_entry | inline_numeric | author_year
    context: str | None = None


class CodeRefRecord(BaseModel):
    page: int
    raw: str
    path: str | None = None
    symbol: str | None = None
    pattern_name: str
    span: list[int] | None = None  # [start, end] within the page text


class MetadataCandidates(BaseModel):
    """Deterministic metadata guesses; the PDF is authoritative but these are
    only candidates — semantic extraction (M4) confirms or rejects them."""

    title: str | None = None
    version_strings: list[str] = Field(default_factory=list)
    date_strings: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    page_count: int
    pages_with_text: int
    pages_without_text: list[int] = Field(default_factory=list)
    total_chars: int
    mean_chars_per_page: float
    heading_count: int
    table_count: int
    equation_count: int
    citation_count: int
    code_reference_count: int
    has_toc: bool
    warnings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    pages: list[PageRecord]
    sections: list[SectionRecord]
    tables: list[TableRecord]
    equations: list[EquationRecord]
    citations: list[CitationRecord]
    code_references: list[CodeRefRecord]
    metadata_candidates: MetadataCandidates
    quality: QualityReport

"""Source evidence tables: artifacts, documents, pages, sections, locators.

Evidence-first rules baked in here:
* artifact_version rows are immutable once written (append-only by convention,
  enforced at the service layer — never update, insert a new version);
* source_locator IDs are deterministic content hashes, so identical evidence
  dedupes across re-ingestion instead of duplicating;
* ``valid_from``/``source_modified_at`` capture source time separately from
  system-recorded ``recorded_at``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modelkb.db.base import Base
from modelkb.db.models.common import (
    ArtifactKind,
    ArtifactOrigin,
    ExtractionStatus,
    LocatorKind,
    RecordedAtMixin,
    UuidPkMixin,
)
from modelkb.db.types import JSONBCompat


class Artifact(UuidPkMixin, RecordedAtMixin, Base):
    """A logical source artifact (e.g. 'the Swiss HPI documentation PDF')."""

    __tablename__ = "artifact"

    uid: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(Enum(ArtifactKind, native_enum=False, length=32))
    origin: Mapped[str] = mapped_column(Enum(ArtifactOrigin, native_enum=False, length=32))
    origin_ref: Mapped[str | None] = mapped_column(String(1024))  # path / SP item id
    display_name: Mapped[str | None] = mapped_column(String(512))

    versions: Mapped[list[ArtifactVersion]] = relationship(back_populates="artifact")


class ArtifactVersion(UuidPkMixin, RecordedAtMixin, Base):
    """One immutable content version of an artifact, addressed by SHA-256."""

    __tablename__ = "artifact_version"
    __table_args__ = (Index("ix_artifact_version_artifact_current", "artifact_id", "is_current"),)

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="RESTRICT"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(128))
    archive_path: Mapped[str] = mapped_column(String(1024))  # immutable archive location
    source_location: Mapped[str | None] = mapped_column(String(1024))
    sharepoint_item_id: Mapped[str | None] = mapped_column(String(255))
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(
        Enum(ExtractionStatus, native_enum=False, length=32), default=ExtractionStatus.pending
    )
    extraction_warnings: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)

    artifact: Mapped[Artifact] = relationship(back_populates="versions")


class Document(UuidPkMixin, RecordedAtMixin, Base):
    """Logical document identity, e.g. document:swiss_hpi."""

    __tablename__ = "document"

    ref: Mapped[str] = mapped_column(String(255), unique=True)
    title_candidate: Mapped[str | None] = mapped_column(String(1024))
    detected_model_ref: Mapped[str | None] = mapped_column(String(255), index=True)

    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")


class DocumentVersion(UuidPkMixin, RecordedAtMixin, Base):
    """A document at a detected documentation version, e.g. docver:swiss_hpi:2026-03."""

    __tablename__ = "document_version"
    __table_args__ = (
        # One doc-version per artifact version: identical labels across
        # revisions are distinct rows (PDFs are authoritative; content wins).
        UniqueConstraint("document_id", "artifact_version_id", name="uq_document_version_artifact"),
    )

    ref: Mapped[str] = mapped_column(String(255), unique=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.id", ondelete="RESTRICT"), index=True
    )
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="RESTRICT")
    )
    version_label: Mapped[str | None] = mapped_column(String(128))  # null until detected
    doc_date: Mapped[str | None] = mapped_column(String(32))  # ISO date string when known
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    document: Mapped[Document] = relationship(back_populates="versions")


class Page(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "page"
    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", name="uq_page_docver_number"),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based, as printed by the PDF
    text_hash: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer)
    extraction_warnings: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)


class Section(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "section"
    __table_args__ = (Index("ix_section_docver_order", "document_version_id", "order_index"),)

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("section.id", ondelete="SET NULL")
    )
    heading_text: Mapped[str] = mapped_column(String(1024))
    heading_path: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)  # root → leaf
    level: Mapped[int] = mapped_column(Integer, default=1)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer)
    detection: Mapped[str] = mapped_column(String(32), default="heuristic")  # heuristic|toc|llm
    confidence: Mapped[float | None] = mapped_column()


class SourceLocator(RecordedAtMixin, Base):
    """The evidence atom. ID is a deterministic hash — see core.ids.evidence_id.

    Locators may be partially populated when the parser could not determine a
    field; ``extraction_limitations`` records what is missing and why.
    """

    __tablename__ = "source_locator"
    __table_args__ = (Index("ix_source_locator_page", "artifact_version_id", "page"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # evidence:<hash16>
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_version.id", ondelete="SET NULL"), index=True
    )
    page: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("section.id", ondelete="SET NULL")
    )
    section_path: Mapped[list[Any] | None] = mapped_column(JSONBCompat)
    kind: Mapped[str] = mapped_column(Enum(LocatorKind, native_enum=False, length=32))
    bounding_box: Mapped[list[Any] | None] = mapped_column(JSONBCompat)  # [x0, y0, x1, y1]
    text_start: Mapped[int | None] = mapped_column(Integer)
    text_end: Mapped[int | None] = mapped_column(Integer)
    table_label: Mapped[str | None] = mapped_column(String(128))
    equation_label: Mapped[str | None] = mapped_column(String(128))
    extracted_text_hash: Mapped[str | None] = mapped_column(String(64))
    extraction_limitations: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)


class ModelInfoSnapshot(UuidPkMixin, RecordedAtMixin, Base):
    """model_info.json ingested as an evidence-bearing source (not truth)."""

    __tablename__ = "model_info_snapshot"

    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="RESTRICT")
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONBCompat)
    model_count: Mapped[int] = mapped_column(Integer, default=0)
    connection_count: Mapped[int] = mapped_column(Integer, default=0)


class ChangeEvent(UuidPkMixin, RecordedAtMixin, Base):
    """Audit log of knowledge-affecting events (ingestions, conflicts, overrides)."""

    __tablename__ = "change_event"
    __table_args__ = (Index("ix_change_event_entity", "entity_ref", "recorded_at"),)

    kind: Mapped[str] = mapped_column(String(64), index=True)
    entity_ref: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )

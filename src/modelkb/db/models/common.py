"""Shared column helpers and enums."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class RecordedAtMixin:
    """System-recorded time (when the KB learned it). Present on every table."""

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class StrEnum(enum.StrEnum):
    """Enum stored as VARCHAR (portable across SQLite/PostgreSQL)."""


class ArtifactKind(StrEnum):
    pdf = "pdf"
    json = "json"
    other = "other"


class ArtifactOrigin(StrEnum):
    local_folder = "local_folder"
    sharepoint = "sharepoint"
    manual = "manual"


class ExtractionStatus(StrEnum):
    pending = "pending"
    success = "success"
    partial = "partial"  # extracted with warnings (e.g. unreadable pages)
    failed = "failed"


class LocatorKind(StrEnum):
    text_span = "text_span"
    table = "table"
    equation = "equation"
    figure = "figure"
    document = "document"  # whole-document evidence when no finer locator exists
    metadata = "metadata"


class RunKind(StrEnum):
    discovery = "discovery"
    pdf_deterministic = "pdf_deterministic"
    schema_proposal = "schema_proposal"
    semantic_extraction = "semantic_extraction"
    model_info_ingest = "model_info_ingest"
    code_inventory = "code_inventory"
    code_linking = "code_linking"
    artifact_generation = "artifact_generation"


class RunStatus(StrEnum):
    running = "running"
    success = "success"
    failed = "failed"


class ReasoningCategory(StrEnum):
    explicit = "explicit"
    inferred_from_text = "inferred_from_text"
    ambiguous = "ambiguous"


class RelationshipStatus(StrEnum):
    proposed = "proposed"
    active = "active"
    superseded = "superseded"
    disputed = "disputed"


class AssertedBy(StrEnum):
    pdf = "pdf"
    model_info_json = "model_info_json"
    human = "human"


class ResolutionStatus(StrEnum):
    unresolved = "unresolved"
    resolved = "resolved"
    ambiguous = "ambiguous"  # several candidate symbols; none chosen
    obsolete = "obsolete"  # matched nothing at the configured git tag


class ReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    needs_changes = "needs_changes"


class LlmInteractionStatus(StrEnum):
    success = "success"
    validation_failed = "validation_failed"
    error = "error"

"""Extraction runs, schema versions, and LLM interaction audit records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from modelkb.db.base import Base
from modelkb.db.models.common import (
    LlmInteractionStatus,
    RecordedAtMixin,
    RunKind,
    RunStatus,
    UuidPkMixin,
)
from modelkb.db.types import JSONBCompat


class ExtractionRun(UuidPkMixin, Base):
    __tablename__ = "extraction_run"

    kind: Mapped[str] = mapped_column(Enum(RunKind, native_enum=False, length=48))
    status: Mapped[str] = mapped_column(
        Enum(RunStatus, native_enum=False, length=32), default=RunStatus.running
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)
    schema_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("schema_version.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchemaVersion(RecordedAtMixin, Base):
    """A versioned extraction schema, persisted as reviewable YAML + JSON Schema.

    Status lifecycle: proposed → active → retired. Nothing derived from an old
    schema is invalidated when a new one appears (baseline stability rule).
    """

    __tablename__ = "schema_version"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. corpus-schema-v1
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    yaml_path: Mapped[str] = mapped_column(String(1024))
    json_path: Mapped[str] = mapped_column(String(1024))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONBCompat)
    created_by: Mapped[str] = mapped_column(String(32), default="llm")  # llm|human
    # use_alter breaks the extraction_run <-> schema_version FK cycle so the
    # constraint is added after both tables exist (required on PostgreSQL).
    proposal_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "extraction_run.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_schema_version_proposal_run_id_extraction_run",
        )
    )
    notes: Mapped[str | None] = mapped_column(Text)


class LlmInteraction(UuidPkMixin, RecordedAtMixin, Base):
    """Full audit record of every LLM call: hashes, versions, failures.

    Request and response payloads are stored verbatim — in a governed system
    the LLM's inputs and outputs are themselves evidence.
    """

    __tablename__ = "llm_interaction"

    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(32))  # chat_only|direct
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Enum(LlmInteractionStatus, native_enum=False, length=32))
    validation_errors: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBCompat)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBCompat)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

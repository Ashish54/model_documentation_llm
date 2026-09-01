"""Knowledge domain: models, claims, assumptions, variables, equations, coefficients.

Versioning pattern (ADR 0001):
* Stable-identity entities get an identity table + version table
  (model/model_version, claim/claim_version — mirroring artifact/artifact_version).
* Leaf concepts (assumption, variable, equation, coefficient) use append-only
  versioned rows: same ``ref``, new row, old row flagged ``is_current=False``.
  Nothing derived from a changing document is ever destructively updated.

Every substantive record links to evidence through a many-to-many association
with source_locator. A record with no evidence is a pipeline bug — the
validation suite (``kb validate-ingestion``) fails on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modelkb.db.base import Base
from modelkb.db.models.common import (
    ReasoningCategory,
    RecordedAtMixin,
    UuidPkMixin,
)
from modelkb.db.types import JSONBCompat

# --- Evidence association tables (many-to-many with source_locator) ---------- #


def _evidence_table(name: str, entity_column: str, entity_table: str) -> Table:
    return Table(
        name,
        Base.metadata,
        Column(
            entity_column,
            Uuid,
            ForeignKey(f"{entity_table}.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        Column(
            "source_locator_id",
            String(80),
            ForeignKey("source_locator.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


claim_version_evidence = _evidence_table(
    "claim_version_evidence", "claim_version_id", "claim_version"
)
assumption_evidence = _evidence_table("assumption_evidence", "assumption_id", "assumption")
variable_evidence = _evidence_table("variable_evidence", "variable_id", "variable")
equation_evidence = _evidence_table("equation_evidence", "equation_id", "equation")
coefficient_evidence = _evidence_table("coefficient_evidence", "coefficient_id", "coefficient")


class Model(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "model"

    ref: Mapped[str] = mapped_column(String(255), unique=True)  # model:swiss_hpi
    name: Mapped[str] = mapped_column(String(512))
    domain: Mapped[str | None] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    versions: Mapped[list[ModelVersion]] = relationship(back_populates="model")


class ModelVersion(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "model_version"
    __table_args__ = (Index("ix_model_version_model_current", "model_id", "is_current"),)

    ref: Mapped[str] = mapped_column(String(255), unique=True)  # modelver:swiss_hpi:2026-03
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model.id", ondelete="RESTRICT"))
    version_label: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))  # pdf|model_info_json|human
    documented_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_version.id", ondelete="SET NULL")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    model: Mapped[Model] = relationship(back_populates="versions")


class Claim(UuidPkMixin, RecordedAtMixin, Base):
    """Stable identity of a claim; content lives in claim_version rows."""

    __tablename__ = "claim"

    ref: Mapped[str] = mapped_column(String(255), unique=True)  # claim:<slug>
    model_ref: Mapped[str | None] = mapped_column(String(255), index=True)
    kind: Mapped[str | None] = mapped_column(String(64))

    versions: Mapped[list[ClaimVersion]] = relationship(back_populates="claim")


class ClaimVersion(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "claim_version"
    __table_args__ = (Index("ix_claim_version_claim_current", "claim_id", "is_current"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
    statement: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning_category: Mapped[str | None] = mapped_column(
        Enum(ReasoningCategory, native_enum=False, length=32)
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )
    schema_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("schema_version.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    claim: Mapped[Claim] = relationship(back_populates="versions")


class _VersionedLeaf(UuidPkMixin, RecordedAtMixin):
    """Append-only versioned leaf record (see module docstring)."""

    ref: Mapped[str] = mapped_column(String(255), index=True)
    model_ref: Mapped[str | None] = mapped_column(String(255), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning_category: Mapped[str | None] = mapped_column(
        Enum(ReasoningCategory, native_enum=False, length=32)
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )
    schema_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("schema_version.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class Assumption(_VersionedLeaf, Base):
    __tablename__ = "assumption"
    __table_args__ = (Index("ix_assumption_ref_current", "ref", "is_current"),)

    name: Mapped[str] = mapped_column(String(512))
    statement: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    materiality: Mapped[str | None] = mapped_column(String(32))  # low|medium|high
    extension: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)


class Variable(_VersionedLeaf, Base):
    __tablename__ = "variable"
    __table_args__ = (Index("ix_variable_ref_current", "ref", "is_current"),)

    name: Mapped[str] = mapped_column(String(512))
    symbol: Mapped[str | None] = mapped_column(String(128))  # mathematical notation
    dtype: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(32))  # input|output|intermediate|parameter
    description: Mapped[str | None] = mapped_column(Text)
    extension: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)


class Equation(_VersionedLeaf, Base):
    __tablename__ = "equation"
    __table_args__ = (Index("ix_equation_ref_current", "ref", "is_current"),)

    label: Mapped[str | None] = mapped_column(String(128))  # "Equation 2"
    raw_text: Mapped[str] = mapped_column(Text)  # as printed
    normalized: Mapped[str | None] = mapped_column(Text)  # normalized form, if derived
    variable_refs: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)
    extension: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)


class Coefficient(_VersionedLeaf, Base):
    __tablename__ = "coefficient"
    __table_args__ = (Index("ix_coefficient_ref_current", "ref", "is_current"),)

    name: Mapped[str] = mapped_column(String(512))
    equation_ref: Mapped[str | None] = mapped_column(String(255))
    value: Mapped[float | None] = mapped_column(Numeric)  # exact numeric when deterministic
    value_text: Mapped[str | None] = mapped_column(String(255))  # raw text as printed
    unit: Mapped[str | None] = mapped_column(String(64))
    extension: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)

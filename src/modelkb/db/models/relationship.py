"""Typed relationship assertions with precedence and conflict retention.

Design (ADR 0002): a relational graph, not a graph database. Conflicting
assertions coexist; a deterministic resolver picks the current view. Nothing
is ever deleted. ``subject_ref``/``object_ref`` are plain strings (not FKs) so
model_info.json can assert relationships about models the PDFs have not yet
established — referential completeness is a validation concern, not a storage
constraint.
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
    Integer,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from modelkb.db.base import Base
from modelkb.db.models.common import (
    AssertedBy,
    RecordedAtMixin,
    RelationshipStatus,
    UuidPkMixin,
)
from modelkb.db.types import JSONBCompat

relationship_evidence = Table(
    "relationship_evidence",
    Base.metadata,
    Column(
        "relationship_id",
        Uuid,
        ForeignKey("relationship.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_locator_id",
        String(80),
        ForeignKey("source_locator.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Initial edge vocabulary. Extensions are additive: register new predicates in
# the active corpus schema YAML; never rename or remove existing ones.
EDGE_VOCABULARY: frozenset[str] = frozenset(
    {
        "depends_on",
        "provides_input_to",
        "produces",
        "consumes",
        "implemented_by",
        "documented_by",
        "calibrated_by",
        "uses_assumption",
        "affects",
        "supersedes",
        "contradicts",
    }
)


class Relationship(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "relationship"
    __table_args__ = (
        # Shaped for future recursive dependency traversal in PostgreSQL:
        # forward walk (subject → object) and reverse walk (object → subject).
        Index("ix_relationship_forward", "subject_ref", "predicate", "status"),
        Index("ix_relationship_reverse", "object_ref", "predicate", "status"),
    )

    subject_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    asserted_by: Mapped[str] = mapped_column(Enum(AssertedBy, native_enum=False, length=32))
    source_precedence: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        Enum(RelationshipStatus, native_enum=False, length=32),
        default=RelationshipStatus.proposed,
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )
    schema_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("schema_version.id", ondelete="SET NULL")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current_view: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    extension: Mapped[dict[str, Any]] = mapped_column(JSONBCompat, default=dict)

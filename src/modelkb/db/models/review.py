"""Extensible review metadata.

Approval workflow is undecided by design; this table adds review capability
without touching history-bearing tables. Attach a review to any record via
(entity_type, entity_ref) — no schema migration needed when new reviewable
entity kinds appear.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from modelkb.db.base import Base
from modelkb.db.models.common import RecordedAtMixin, ReviewStatus, UuidPkMixin


class ReviewState(UuidPkMixin, RecordedAtMixin, Base):
    __tablename__ = "review_state"
    __table_args__ = (Index("ix_review_state_entity", "entity_type", "entity_ref", "is_current"),)

    entity_type: Mapped[str] = mapped_column(String(64))  # claim|assumption|relationship|...
    entity_ref: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        Enum(ReviewStatus, native_enum=False, length=32), default=ReviewStatus.pending
    )
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comments: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

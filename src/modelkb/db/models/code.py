"""Python-library inventory and documentation code references.

The inventory is taken at exactly one configured Git tag (recorded with its
resolved commit). Code references found in PDFs are linked to symbols where
possible; unresolved/ambiguous/obsolete references are recorded, never guessed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from modelkb.db.base import Base
from modelkb.db.models.common import RecordedAtMixin, ResolutionStatus, UuidPkMixin
from modelkb.db.types import JSONBCompat

code_reference_evidence = Table(
    "code_reference_evidence",
    Base.metadata,
    Column(
        "code_reference_id",
        Uuid,
        ForeignKey("code_reference.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_locator_id",
        String(80),
        ForeignKey("source_locator.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class CodeSymbol(UuidPkMixin, RecordedAtMixin, Base):
    """A symbol inventoried from the configured Git tag — evidence, not execution."""

    __tablename__ = "code_symbol"
    __table_args__ = (
        UniqueConstraint("git_commit", "path", "qualname", name="uq_code_symbol_location"),
        Index("ix_code_symbol_lookup", "path", "qualname"),
    )

    ref: Mapped[str] = mapped_column(String(1024), unique=True)  # code:<commit>:<path>#<qualname>
    git_tag: Mapped[str] = mapped_column(String(255))
    git_commit: Mapped[str] = mapped_column(String(64))
    repo_origin: Mapped[str | None] = mapped_column(String(1024))  # path or URL used
    path: Mapped[str] = mapped_column(String(1024))
    qualname: Mapped[str] = mapped_column(String(1024))  # module.Class.method
    kind: Mapped[str] = mapped_column(String(32))  # package|module|class|function|method|constant
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    imports: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)  # module rows only
    constant_value: Mapped[str | None] = mapped_column(Text)  # repr, truncated


class CodeReference(UuidPkMixin, RecordedAtMixin, Base):
    """A code-path or Python-symbol mention found in documentation."""

    __tablename__ = "code_reference"
    __table_args__ = (Index("ix_code_reference_status", "resolution_status", "is_current"),)

    raw_text: Mapped[str] = mapped_column(Text)  # exactly as printed
    normalized_path: Mapped[str | None] = mapped_column(String(1024))
    symbol_candidate: Mapped[str | None] = mapped_column(String(1024))
    pattern_name: Mapped[str | None] = mapped_column(String(128))  # which config pattern hit
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_version.id", ondelete="SET NULL"), index=True
    )
    git_tag: Mapped[str | None] = mapped_column(String(255))  # tag used for resolution
    resolution_status: Mapped[str] = mapped_column(
        Enum(ResolutionStatus, native_enum=False, length=32), default=ResolutionStatus.unresolved
    )
    resolved_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbol.id", ondelete="SET NULL")
    )
    candidate_symbol_ids: Mapped[list[Any]] = mapped_column(JSONBCompat, default=list)
    is_current: Mapped[bool] = mapped_column(default=True)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_run.id", ondelete="SET NULL")
    )

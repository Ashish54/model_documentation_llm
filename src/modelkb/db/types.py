"""Portable column types: production PostgreSQL, test SQLite.

``JSONBCompat`` maps to JSONB on PostgreSQL (indexable, server-side JSON ops)
and plain JSON on SQLite. Application code never branches on the dialect.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class JSONBCompat(TypeDecorator[Any]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

"""Persist LLM interaction records to the database (one row per call)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.engine import Engine

from modelkb.db import models as m
from modelkb.db.session import session_scope
from modelkb.llm.base import InteractionRecord


def make_db_recorder(engine: Engine) -> Callable[[InteractionRecord], None]:
    def record(interaction: InteractionRecord) -> None:
        with session_scope(engine) as session:
            session.add(m.LlmInteraction(**interaction.__dict__))

    return record

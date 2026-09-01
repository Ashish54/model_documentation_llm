"""Database bootstrap: apply Alembic migrations programmatically."""

from __future__ import annotations

from pathlib import Path

import alembic.config
from alembic.command import upgrade
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from modelkb.db.session import make_engine

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def init_db(url: str | None = None) -> tuple[Engine, int]:
    """Run migrations to head; return (engine, table_count)."""
    if url and url.startswith("sqlite"):
        Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    ini = _PROJECT_ROOT / "alembic.ini"
    if not ini.exists():
        raise FileNotFoundError(f"alembic.ini not found at {ini}")
    alembic_cfg = alembic.config.Config(str(ini), attributes={"url": url} if url else {})
    alembic_cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    upgrade(alembic_cfg, "head")
    engine = make_engine(url)
    return engine, len(inspect(engine).get_table_names())

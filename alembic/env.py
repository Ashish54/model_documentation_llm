"""Alembic environment: metadata comes from the ORM, URL from typed config.

Override the URL without touching config for tests/one-offs:
    alembic -x dburl=sqlite:////tmp/test.db upgrade head
"""

from __future__ import annotations

import modelkb.db.models  # noqa: F401 — registers all tables on Base.metadata
from alembic import context
from modelkb.core.config import get_settings
from modelkb.db.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config

target_metadata = Base.metadata


def _url() -> str:
    attr = config.attributes.get("url")  # programmatic override (init_db, tests)
    if attr:
        return attr
    x_args = context.get_x_argument(as_dictionary=True)
    if "dburl" in x_args:
        return x_args["dburl"]
    return get_settings().database.url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-safe ALTERs; harmless on PostgreSQL
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

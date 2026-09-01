"""Engine and session factories.

Everything goes through ``session_scope`` so transaction boundaries are
explicit and consistent between CLI, tests, and the future API service.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from modelkb.core.config import get_settings


def make_engine(url: str | None = None, *, echo: bool | None = None) -> Engine:
    settings = get_settings()
    url = url or settings.database.url
    echo = settings.database.echo if echo is None else echo
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=echo, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Provide a transactional scope; commit on success, rollback on error."""
    factory = make_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

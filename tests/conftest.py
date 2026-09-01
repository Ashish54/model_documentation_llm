"""Shared pytest fixtures: isolated SQLite database and settings per test."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from modelkb.core.config import Settings, get_settings
from modelkb.db.init import init_db
from modelkb.db.session import session_scope


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/test.db"


@pytest.fixture()
def engine(db_url: str) -> Engine:
    eng, table_count = init_db(db_url)
    assert table_count > 30, f"expected full schema, got {table_count} tables"
    return eng


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    with session_scope(engine) as s:
        yield s


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings rooted at a temp dir, independent of config/settings.yaml."""
    monkeypatch.setenv("KB_PATHS__INPUT_DIR", str(tmp_path / "input"))
    monkeypatch.setenv("KB_PATHS__ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("KB_PATHS__EXTRACTIONS_DIR", str(tmp_path / "extractions"))
    monkeypatch.setenv("KB_PATHS__KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("KB_PATHS__OUTPUT_REPO_PATH", str(tmp_path / "output"))
    monkeypatch.setenv("KB_DATABASE__URL", f"sqlite:///{tmp_path}/test.db")
    return get_settings(refresh=True)


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    yield
    get_settings(refresh=True)

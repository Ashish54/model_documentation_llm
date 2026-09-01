import os
from pathlib import Path

import pytest

from modelkb.archive.store import ArtifactStore
from modelkb.core.hashing import sha256_file


def test_put_archives_by_content_hash(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-fake-content")
    store = ArtifactStore(tmp_path / "archive")

    rec = store.put(src)
    assert rec.sha256 == sha256_file(src)
    assert not rec.already_present
    assert rec.archive_path.exists()
    assert rec.archive_path.name == rec.sha256
    assert rec.archive_path.parent.name == rec.sha256[:2]


def test_put_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"same bytes")
    store = ArtifactStore(tmp_path / "archive")

    first = store.put(src)
    second = store.put(src)
    assert first.sha256 == second.sha256
    assert second.already_present


def test_archived_file_is_read_only(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"evidence")
    store = ArtifactStore(tmp_path / "archive")
    rec = store.put(src)
    mode = os.stat(rec.archive_path).st_mode
    assert not mode & 0o200, "archived evidence must not be writable"


def test_open_missing_raises(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "archive")
    with pytest.raises(FileNotFoundError):
        store.open("0" * 64)

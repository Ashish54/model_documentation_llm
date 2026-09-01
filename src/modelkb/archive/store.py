"""Immutable, content-addressed artifact store.

Layout: ``<archive_dir>/<sha256[:2]>/<sha256>`` — the original bytes, written
once, never mutated. Re-archiving the same content is a no-op that returns the
existing record (idempotent ingestion).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from modelkb.core.hashing import sha256_file


@dataclass(frozen=True)
class ArchivedFile:
    sha256: str
    size_bytes: int
    archive_path: Path
    already_present: bool


class ArtifactStore:
    def __init__(self, archive_dir: Path) -> None:
        self._root = archive_dir

    def _dest(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256

    def put(self, source: Path) -> ArchivedFile:
        """Copy ``source`` into the store under its content hash."""
        digest = sha256_file(source)
        dest = self._dest(digest)
        if dest.exists():
            existing = sha256_file(dest)
            if existing != digest:  # pragma: no cover - defensive: hash collision/corruption
                raise RuntimeError(
                    f"archive integrity failure: {dest} has hash {existing}, expected {digest}"
                )
            return ArchivedFile(digest, dest.stat().st_size, dest, already_present=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(source, tmp)
        tmp.replace(dest)  # atomic publish
        dest.chmod(0o444)  # read-only: evidence is immutable
        return ArchivedFile(digest, dest.stat().st_size, dest, already_present=False)

    def open(self, sha256: str) -> Path:
        dest = self._dest(sha256)
        if not dest.exists():
            raise FileNotFoundError(f"artifact {sha256} not in archive at {dest}")
        return dest

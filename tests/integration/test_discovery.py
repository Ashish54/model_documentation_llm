"""End-to-end discovery tests: archive → parse → package → DB → report.

Also covers required-test #3 (prior artifact versions are preserved) at the
artifact level: re-ingesting changed content adds a version, never rewrites.
"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from modelkb.db import models as m
from modelkb.db.init import init_db
from modelkb.db.session import session_scope
from modelkb.discovery.service import run_discovery
from tests.fixtures.synthetic_pdfs import make_corpus


@pytest.fixture()
def corpus_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "input"
    make_corpus(directory)
    return directory


def _counts(engine) -> dict[str, int]:
    with session_scope(engine) as session:
        return {
            name: session.scalar(select(func.count()).select_from(table))
            for name, table in {
                "artifact": m.Artifact,
                "artifact_version": m.ArtifactVersion,
                "document": m.Document,
                "document_version": m.DocumentVersion,
                "page": m.Page,
                "section": m.Section,
                "source_locator": m.SourceLocator,
            }.items()
        }


def test_discovery_end_to_end(settings, corpus_dir: Path, tmp_path: Path) -> None:
    engine, _ = init_db(settings.database.url)
    result = run_discovery(input_dir=corpus_dir, engine=engine)

    assert result.documents_analyzed == 4
    report = json.loads(result.report_path.read_text())
    assert report["aggregate"]["document_count"] == 4
    assert report["aggregate"]["documents_with_toc"] == 1
    assert "pension.pdf" in report["aggregate"]["documents_with_warnings"]
    # varied structures must surface in the aggregate (drives the schema later)
    assert len(report["aggregate"]["common_headings"]) > 0
    assert report["aggregate"]["all_code_reference_paths"]

    counts = _counts(engine)
    assert counts["artifact"] == 4
    assert counts["artifact_version"] == 4
    assert counts["document"] == 4
    assert counts["page"] >= 7
    assert counts["section"] >= 10
    assert counts["source_locator"] > 0

    # extraction packages written per artifact
    packages = list((tmp_path / "extractions").glob("*/manifest.json"))
    assert len(packages) == 4
    manifest = json.loads(packages[0].read_text())
    assert manifest["parser"]["name"] == "pymupdf"


def test_discovery_is_idempotent(settings, corpus_dir: Path) -> None:
    engine, _ = init_db(settings.database.url)
    run_discovery(input_dir=corpus_dir, engine=engine)
    second = run_discovery(input_dir=corpus_dir, engine=engine)
    assert second.documents_analyzed == 0
    assert second.documents_skipped_unchanged == 4
    assert _counts(engine)["artifact_version"] == 4  # nothing duplicated


def test_changed_content_adds_version_and_preserves_prior(settings, corpus_dir: Path) -> None:
    engine, _ = init_db(settings.database.url)
    run_discovery(input_dir=corpus_dir, engine=engine)

    # Modify one PDF (new content ⇒ new sha ⇒ new version).
    import pymupdf as fitz

    from tests.fixtures.synthetic_pdfs import BODY, H1, _write_lines

    modified = corpus_dir / "macro_core_v2.pdf"
    shutil.copy(corpus_dir / "macro_core.pdf", modified)
    modified.rename(corpus_dir / "macro_core.pdf")
    doc = fitz.open(corpus_dir / "macro_core.pdf")
    page = doc.new_page()
    _write_lines(page, [("4 Appendix", H1), ("Added in the revised edition.", BODY)])
    doc.saveIncr()
    doc.close()

    run_discovery(input_dir=corpus_dir, engine=engine)

    with session_scope(engine) as session:
        versions = session.scalars(
            select(m.ArtifactVersion)
            .join(m.Artifact)
            .where(m.Artifact.origin_ref == "macro_core.pdf")
            .order_by(m.ArtifactVersion.recorded_at)
        ).all()
        assert len(versions) == 2, "prior version must be preserved"
        current = [v for v in versions if v.is_current]
        assert len(current) == 1
        assert current[0].page_count == 3
        superseded = [v for v in versions if not v.is_current]
        assert superseded[0].page_count == 2  # old evidence untouched

        events = session.scalars(
            select(m.ChangeEvent).where(m.ChangeEvent.kind == "artifact_version_added")
        ).all()
        assert len(events) == 1

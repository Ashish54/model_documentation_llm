"""Pass A: corpus discovery.

For every candidate from the configured document source:
  archive immutably → upsert artifact/artifact_version → deterministic parse →
  write the extraction package → persist pages/sections/evidence locators →
  accumulate a per-document structural summary → emit the discovery report.

Idempotent by construction: content already archived under the same SHA is
skipped (and reported as such), so re-running discovery is cheap and safe.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from modelkb.archive.store import ArtifactStore
from modelkb.core.config import ParserSettings, get_settings, resolve_path
from modelkb.core.ids import document_ref, document_version_ref, evidence_id, model_ref, slugify
from modelkb.core.logging import get_logger
from modelkb.db import models as m
from modelkb.db.init import init_db
from modelkb.db.models.common import (
    ArtifactKind,
    ArtifactOrigin,
    ExtractionStatus,
    LocatorKind,
    RunKind,
    RunStatus,
)
from modelkb.db.session import session_scope
from modelkb.discovery.report import CorpusAggregate, DiscoveryReport, DocumentSummary
from modelkb.extraction.package import write_extraction_package
from modelkb.pdf.models import ParsedDocument
from modelkb.pdf.pymupdf_parser import PyMuPdfParser
from modelkb.sources.local_folder import LocalFolderSource

log = get_logger("discovery")

_RELATIONSHIP_HINT_RE = re.compile(
    r"\b(uses|depends on|input (?:from|to)|produced by|feeds into|calibrated (?:by|with)|"
    r"drives|consumes|output of)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiscoveryResult:
    run_id: str
    documents_analyzed: int
    documents_skipped_unchanged: int
    report_path: Path


def run_discovery(
    *, input_dir: Path | None = None, engine: Engine | None = None
) -> DiscoveryResult:
    settings = get_settings()
    input_dir = input_dir or resolve_path(settings.paths.input_dir)
    extractions_dir = resolve_path(settings.paths.extractions_dir)
    archive = ArtifactStore(resolve_path(settings.paths.archive_dir))
    parser = PyMuPdfParser(settings.parser)
    source = LocalFolderSource(input_dir, patterns=("*.pdf",))

    if engine is None:
        engine, _ = init_db(settings.database.url)

    run = m.ExtractionRun(
        kind=RunKind.discovery,
        params={"input_dir": str(input_dir)},
        tool_versions={"pymupdf": parser.version, "modelkb": _modelkb_version()},
    )
    summaries: list[DocumentSummary] = []
    skipped = 0

    with session_scope(engine) as session:
        session.add(run)
        session.flush()  # run.id available for child rows
        run_id = run.id

        for candidate in source.iter_candidates():
            log.info("discovering", candidate=candidate.name)
            try:
                # Savepoint per candidate: one malformed document must not
                # poison the batch transaction.
                with session.begin_nested():
                    summary, was_skipped = _discover_one(
                        session=session,
                        candidate_path=source.fetch(candidate),
                        origin=ArtifactOrigin.local_folder,
                        origin_ref=candidate.origin_ref,
                        source_modified_at=candidate.modified_at,
                        archive=archive,
                        parser=parser,
                        extractions_dir=extractions_dir,
                        run_id=run_id,
                        parser_settings=settings.parser,
                    )
            except Exception as exc:  # one bad PDF must not kill the corpus pass
                log.error(
                    "discovery failed for candidate",
                    candidate=candidate.name,
                    error=str(exc),
                )
                session.add(
                    m.ChangeEvent(
                        kind="discovery_failure",
                        entity_ref=candidate.origin_ref,
                        summary=f"discovery failed for {candidate.name}: {exc}",
                        extraction_run_id=run_id,
                    )
                )
                continue
            if was_skipped:
                skipped += 1
            if summary is not None:
                summaries.append(summary)

        report = DiscoveryReport(
            run_id=str(run_id),
            input_dir=str(input_dir),
            documents=summaries,
            aggregate=_aggregate(summaries),
        )
        report_dir = extractions_dir / "discovery" / str(run_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "discovery_report.json"
        report_path.write_text(report.model_dump_json(indent=2) + "\n")

        run.status = RunStatus.success
        run.stats = {
            "documents_analyzed": len(summaries),
            "documents_skipped_unchanged": skipped,
            "report_path": str(report_path),
        }
        run.finished_at = datetime.now(UTC)

    return DiscoveryResult(
        run_id=str(run_id),
        documents_analyzed=len(summaries),
        documents_skipped_unchanged=skipped,
        report_path=report_path,
    )


def _discover_one(
    *,
    session: Session,
    candidate_path: Path,
    origin: ArtifactOrigin,
    origin_ref: str,
    source_modified_at: datetime | None,
    archive: ArtifactStore,
    parser: PyMuPdfParser,
    extractions_dir: Path,
    run_id: uuid.UUID,
    parser_settings: ParserSettings,
) -> tuple[DocumentSummary | None, bool]:
    archived = archive.put(candidate_path)

    artifact_uid = f"{origin}:{origin_ref}"
    artifact = session.scalar(select(m.Artifact).where(m.Artifact.uid == artifact_uid))
    if artifact is None:
        artifact = m.Artifact(
            uid=artifact_uid,
            kind=ArtifactKind.pdf,
            origin=origin,
            origin_ref=origin_ref,
            display_name=candidate_path.name,
        )
        session.add(artifact)
        session.flush()

    existing_version = session.scalar(
        select(m.ArtifactVersion).where(m.ArtifactVersion.sha256 == archived.sha256)
    )
    if existing_version is not None:
        log.info("content already archived; skipping", sha256=archived.sha256[:12])
        if existing_version.artifact_id != artifact.id:
            # Same bytes under a different source name: one evidence copy is
            # enough, but record the duplicate sighting for traceability.
            session.add(
                m.ChangeEvent(
                    kind="duplicate_content_observed",
                    entity_ref=artifact_uid,
                    summary=f"{candidate_path.name} has identical content to an "
                    f"already-archived artifact ({archived.sha256[:12]})",
                    payload={"sha256": archived.sha256, "duplicate_of": existing_version.id.hex},
                    extraction_run_id=run_id,
                )
            )
        return None, True

    current = session.scalar(
        select(m.ArtifactVersion).where(
            m.ArtifactVersion.artifact_id == artifact.id, m.ArtifactVersion.is_current.is_(True)
        )
    )
    if current is not None:
        current.is_current = False
        session.add(
            m.ChangeEvent(
                kind="artifact_version_added",
                entity_ref=artifact_uid,
                summary=f"new content version {archived.sha256[:12]} supersedes "
                f"{current.sha256[:12]}",
                payload={"new_sha256": archived.sha256, "old_sha256": current.sha256},
                extraction_run_id=run_id,
            )
        )

    parsed = parser.parse(candidate_path)
    status = ExtractionStatus.partial if parsed.quality.warnings else ExtractionStatus.success
    version = m.ArtifactVersion(
        artifact_id=artifact.id,
        sha256=archived.sha256,
        size_bytes=archived.size_bytes,
        media_type="application/pdf",
        archive_path=str(archived.archive_path),
        source_location=str(candidate_path),
        source_modified_at=source_modified_at,
        is_current=True,
        page_count=parsed.quality.page_count,
        parser_name=parser.name,
        parser_version=parser.version,
        extraction_status=status,
        extraction_warnings=parsed.quality.warnings,
    )
    session.add(version)
    session.flush()

    write_extraction_package(
        parsed,
        artifact_sha256=archived.sha256,
        source_name=candidate_path.name,
        parser_name=parser.name,
        parser_version=parser.version,
        parser_settings=parser_settings,
        extractions_dir=extractions_dir,
    )

    document, doc_version = _persist_document_structure(
        session,
        parsed=parsed,
        artifact_version=version,
        source_name=candidate_path.name,
        run_id=run_id,
    )
    summary = _summarize(
        parsed,
        artifact=version,
        document=document,
        doc_version=doc_version,
        source_name=candidate_path.name,
    )
    return summary, False


def _persist_document_structure(
    session: Session,
    *,
    parsed: ParsedDocument,
    artifact_version: m.ArtifactVersion,
    source_name: str,
    run_id: uuid.UUID,
) -> tuple[m.Document, m.DocumentVersion]:
    slug = slugify(Path(source_name).stem)
    dref = document_ref(slug)
    document = session.scalar(select(m.Document).where(m.Document.ref == dref))
    if document is None:
        document = m.Document(
            ref=dref,
            title_candidate=parsed.metadata_candidates.title,
            detected_model_ref=model_ref(slug),  # provisional until M4 confirms from content
        )
        session.add(document)
        session.flush()

    label = (
        parsed.metadata_candidates.version_strings[0]
        if parsed.metadata_candidates.version_strings
        else None
    )
    dvref = document_version_ref(slug, label or f"unversioned-{artifact_version.sha256[:8]}")
    if session.scalar(select(m.DocumentVersion).where(m.DocumentVersion.ref == dvref)):
        # Same label, new content: a revision of the labeled version.
        dvref = f"{dvref}-r{artifact_version.sha256[:8]}"

    # Prior doc-versions step down; history is preserved, currency moves.
    prior_versions = session.scalars(
        select(m.DocumentVersion).where(
            m.DocumentVersion.document_id == document.id,
            m.DocumentVersion.is_current.is_(True),
        )
    ).all()
    for prior in prior_versions:
        prior.is_current = False

    doc_version = m.DocumentVersion(
        ref=dvref,
        document_id=document.id,
        artifact_version_id=artifact_version.id,
        version_label=label,
        doc_date=parsed.metadata_candidates.date_strings[0]
        if parsed.metadata_candidates.date_strings
        else None,
        is_current=True,
    )
    session.add(doc_version)
    session.flush()

    for page in parsed.pages:
        session.add(
            m.Page(
                document_version_id=doc_version.id,
                page_number=page.page_number,
                text_hash=page.text_hash,
                char_count=page.char_count,
                extraction_warnings=page.warnings,
            )
        )

    section_ids: dict[tuple[str, ...], uuid.UUID] = {}
    for section in parsed.sections:
        path_tuple = tuple(section.heading_path)
        parent = section_ids.get(path_tuple[:-1])
        row = m.Section(
            document_version_id=doc_version.id,
            parent_id=parent,
            heading_text=section.heading,
            heading_path=section.heading_path,
            level=section.level,
            page_start=section.page_start,
            page_end=section.page_end,
            order_index=section.order_index,
            detection=section.detection,
            confidence=section.confidence,
        )
        session.add(row)
        session.flush()
        section_ids[path_tuple] = row.id

    _ID_FIELDS = {
        "kind",
        "page",
        "text_start",
        "text_end",
        "extracted_text_hash",
        "table_label",
        "equation_label",
    }

    def add_locator(**kwargs: Any) -> None:
        id_kwargs = {k: v for k, v in kwargs.items() if k in _ID_FIELDS}
        id_kwargs.setdefault("kind", LocatorKind.text_span)
        eid = evidence_id(artifact_version.sha256, **id_kwargs)
        if session.get(m.SourceLocator, eid) is None:
            session.add(
                m.SourceLocator(
                    id=eid,
                    artifact_version_id=artifact_version.id,
                    document_version_id=doc_version.id,
                    **kwargs,
                )
            )

    add_locator(kind=LocatorKind.document, page=None)
    for table in parsed.tables:
        add_locator(
            kind=LocatorKind.table,
            page=table.page,
            bounding_box=table.bbox,
            table_label=table.label,
            extracted_text_hash=_rows_hash(table.header, table.rows),
        )
    for equation in parsed.equations:
        add_locator(
            kind=LocatorKind.equation,
            page=equation.page,
            bounding_box=equation.bbox,
            equation_label=equation.label,
            extracted_text_hash=_text_hash(equation.text),
        )
    for ref in parsed.code_references:
        add_locator(
            kind=LocatorKind.text_span,
            page=ref.page,
            text_start=ref.span[0] if ref.span else None,
            text_end=ref.span[1] if ref.span else None,
            extracted_text_hash=_text_hash(ref.raw),
        )
    return document, doc_version


def _summarize(
    parsed: ParsedDocument,
    *,
    artifact: m.ArtifactVersion,
    document: m.Document,
    doc_version: m.DocumentVersion,
    source_name: str,
) -> DocumentSummary:
    relationship_lines = [
        line.strip()
        for page in parsed.pages
        for line in page.text.splitlines()
        if _RELATIONSHIP_HINT_RE.search(line)
    ][:10]
    return DocumentSummary(
        artifact_sha256=artifact.sha256,
        source_name=source_name,
        document_ref=document.ref,
        document_version_ref=doc_version.ref,
        title_candidate=parsed.metadata_candidates.title,
        metadata_candidates=parsed.metadata_candidates.model_dump(),
        page_count=parsed.quality.page_count,
        has_toc=parsed.quality.has_toc,
        headings=[
            {"path": s.heading_path, "level": s.level, "page": s.page_start}
            for s in parsed.sections
        ],
        table_shapes=[
            {"label": t.label, "n_rows": t.n_rows, "n_cols": t.n_cols, "page": t.page}
            for t in parsed.tables
        ],
        equation_labels=[e.label for e in parsed.equations if e.label],
        citation_count=len(parsed.citations),
        code_references=[
            {"raw": c.raw, "path": c.path, "symbol": c.symbol, "page": c.page}
            for c in parsed.code_references
        ],
        relationship_language=relationship_lines,
        extraction_warnings=parsed.quality.warnings,
        quality=parsed.quality.model_dump(),
    )


def _aggregate(summaries: list[DocumentSummary]) -> CorpusAggregate:
    heading_counter: dict[str, int] = {}
    for summary in summaries:
        seen_in_doc: set[str] = set()
        for heading in summary.headings:
            leaf = _normalize_heading(heading["path"][-1])
            if leaf not in seen_in_doc:
                heading_counter[leaf] = heading_counter.get(leaf, 0) + 1
                seen_in_doc.add(leaf)
    common = [
        {"heading": h, "documents": n}
        for h, n in sorted(heading_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    shapes = {f"{t['n_rows']}x{t['n_cols']}" for s in summaries for t in s.table_shapes}
    label_styles = sorted(
        {label.split()[0] for s in summaries for label in s.equation_labels if label}
    )
    code_paths = sorted({c["path"] for s in summaries for c in s.code_references if c.get("path")})
    return CorpusAggregate(
        document_count=len(summaries),
        documents_with_toc=sum(1 for s in summaries if s.has_toc),
        documents_with_warnings=[s.source_name for s in summaries if s.extraction_warnings],
        common_headings=common,
        distinct_table_shapes=sorted(shapes),
        equation_label_styles=label_styles,
        all_code_reference_paths=code_paths,
        total_pages=sum(s.page_count for s in summaries),
    )


def _normalize_heading(text: str) -> str:
    return re.sub(r"^\d+(\.\d+)*[.)]?\s*", "", text.strip()).lower()


def _rows_hash(header: list[str], rows: list[list[str]]) -> str:
    from modelkb.core.hashing import sha256_text

    return sha256_text(json.dumps([header, *rows], ensure_ascii=False))


def _text_hash(text: str) -> str:
    from modelkb.core.hashing import sha256_text

    return sha256_text(text)


def _modelkb_version() -> str:
    from modelkb import __version__

    return __version__

"""kb — command-line interface for the model knowledge-base ingestion pipeline.

Milestone status:
  implemented now : discover-corpus, propose-schema, validate-schema, db-init, report(basic)
  milestone 4     : ingest-pdfs (schema-guided semantic extraction)
  milestone 5     : ingest-model-info (relationship conflicts)
  milestone 6     : inventory-code, link-code-references
  milestone 7     : generate-knowledge-artifacts
  milestone 8     : validate-ingestion (full), inspection API
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from modelkb.core.config import get_settings
from modelkb.core.logging import configure_logging, get_logger

app = typer.Typer(
    name="kb",
    help="Governed ingestion pipeline for the financial-model knowledge base.",
    no_args_is_help=True,
)
log = get_logger("cli")


@app.callback()
def _main(verbose: bool = False, json_logs: bool = False) -> None:
    configure_logging(level="DEBUG" if verbose else "INFO", json_output=json_logs)


def _not_yet(milestone: str) -> None:
    typer.secho(
        f"This command is scheduled for {milestone}. The interface is fixed; "
        "the implementation lands with that milestone.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=2)


# --- Implemented in milestones 1-3 ------------------------------------------- #


@app.command()
def db_init() -> None:
    """Create database tables (equivalent to `alembic upgrade head`)."""
    from modelkb.db.init import init_db

    engine, created = init_db()
    typer.echo(f"database ready: {engine.url} ({created} tables)")


@app.command()
def discover_corpus(
    input: Annotated[Path | None, typer.Option("--input", help="PDF directory")] = None,
) -> None:
    """Pass A: deterministic structural analysis of every PDF in the corpus."""
    from modelkb.discovery.service import run_discovery

    result = run_discovery(input_dir=input)
    typer.echo(
        f"discovery run {result.run_id}: {result.documents_analyzed} documents analyzed; "
        f"report at {result.report_path}"
    )


@app.command()
def propose_schema(
    discovery_run: Annotated[str, typer.Option("--discovery-run", help="Discovery run ID")],
) -> None:
    """Pass A (LLM): propose a corpus schema from a discovery report."""
    from modelkb.schema.proposal import run_schema_proposal

    proposal = run_schema_proposal(discovery_run_id=discovery_run)
    typer.echo(
        f"schema proposal persisted as {proposal.schema_id} "
        f"(yaml: {proposal.yaml_path}); review it, then activate with validate-schema"
    )


@app.command()
def validate_schema(
    schema: Annotated[Path, typer.Option("--schema", help="Path to schema YAML")],
    activate: Annotated[
        bool, typer.Option("--activate", help="Mark as the active schema after validation")
    ] = False,
) -> None:
    """Validate a schema artifact (YAML + JSON Schema + base components)."""
    from modelkb.schema.registry import validate_schema_file

    result = validate_schema_file(schema, activate=activate)
    if result.ok:
        typer.secho(
            f"schema {result.schema_id} is valid" + (" and now active" if activate else ""),
            fg=typer.colors.GREEN,
        )
    else:
        for err in result.errors:
            typer.secho(f"  ✗ {err}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


# --- Later milestones (fixed interfaces, explicit stubs) ---------------------- #


@app.command()
def ingest_pdfs(
    input: Annotated[Path | None, typer.Option("--input")] = None,
    schema: Annotated[str | None, typer.Option("--schema", help="Schema version")] = None,
) -> None:
    """Pass B: schema-guided semantic extraction across all PDFs. (milestone 4)"""
    _not_yet("milestone 4 (schema-guided semantic extraction)")


@app.command()
def ingest_model_info(
    path: Annotated[Path, typer.Option("--path", help="Path to model_info.json")],
) -> None:
    """Ingest model_info.json as an evidence-bearing source. (milestone 5)"""
    _not_yet("milestone 5 (model_info.json ingestion + conflict handling)")


@app.command()
def inventory_code(
    repo: Annotated[Path | None, typer.Option("--repo")] = None,
    git_tag: Annotated[str | None, typer.Option("--git-tag")] = None,
) -> None:
    """AST inventory of the Python library at the configured Git tag. (milestone 6)"""
    _not_yet("milestone 6 (code inventory)")


@app.command()
def link_code_references() -> None:
    """Map documentation code references to inventoried symbols. (milestone 6)"""
    _not_yet("milestone 6 (code-reference linking)")


@app.command()
def generate_knowledge_artifacts() -> None:
    """Render reviewable Markdown/YAML knowledge artifacts. (milestone 7)"""
    _not_yet("milestone 7 (artifact generation)")


@app.command()
def validate_ingestion() -> None:
    """Run the full evidence/integrity validation suite. (milestone 8)"""
    _not_yet("milestone 8 (validation suite)")


@app.command()
def report() -> None:
    """Print a summary of the knowledge-base state."""
    from sqlalchemy import func, select

    from modelkb.db import models as m
    from modelkb.db.init import init_db
    from modelkb.db.session import session_scope

    engine, _ = init_db()
    with session_scope(engine) as session:
        counts = {
            table: session.scalar(select(func.count()).select_from(table))
            for table in (
                m.Artifact,
                m.ArtifactVersion,
                m.Document,
                m.DocumentVersion,
                m.SourceLocator,
                m.ExtractionRun,
                m.SchemaVersion,
                m.LlmInteraction,
            )
        }
    typer.echo("knowledge-base state:")
    for table, count in counts.items():
        typer.echo(f"  {table.__tablename__:<22} {count}")
    settings = get_settings()
    typer.echo(f"active schema: {settings.schema_.active_version or '(none)'}")

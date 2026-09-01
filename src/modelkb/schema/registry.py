"""Schema registry: persist, validate, and activate corpus schemas.

Storage is three-way and deliberate:
* YAML artifact   — the human-reviewable source of truth (knowledge/schema/)
* JSON Schema     — machine-checkable contract for extraction outputs
* schema_version  — DB row for status (proposed/active/retired) and lineage
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from modelkb.core.config import get_settings, resolve_path
from modelkb.db import models as m
from modelkb.db.session import session_scope
from modelkb.schema.models import CorpusSchema


def schema_dir(knowledge_dir: Path | None = None) -> Path:
    if knowledge_dir is None:
        knowledge_dir = resolve_path(get_settings().paths.knowledge_dir)
    directory = knowledge_dir / "schema"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def next_schema_id(session: Session, prefix: str = "corpus-schema-v") -> str:
    existing = session.scalars(select(m.SchemaVersion.id)).all()
    highest = 0
    for schema_id in existing:
        if schema_id.startswith(prefix):
            try:
                highest = max(highest, int(schema_id[len(prefix) :]))
            except ValueError:
                continue
    return f"{prefix}{highest + 1}"


def persist_schema(
    schema: CorpusSchema,
    *,
    engine: Engine,
    knowledge_dir: Path | None = None,
    proposal_run_id: uuid.UUID | None = None,
) -> tuple[Path, Path]:
    """Write YAML + JSON Schema artifacts and upsert the schema_version row."""
    directory = schema_dir(knowledge_dir)
    yaml_path = directory / f"{schema.schema_id}.yaml"
    json_path = directory / f"{schema.schema_id}.json"

    yaml_path.write_text(
        yaml.safe_dump(schema.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    )
    json_path.write_text(json.dumps(schema.to_json_schema(), indent=2) + "\n")

    with session_scope(engine) as session:
        row = session.get(m.SchemaVersion, schema.schema_id)
        if row is None:
            row = m.SchemaVersion(id=schema.schema_id)
        row.status = schema.status
        row.yaml_path = str(yaml_path)
        row.json_path = str(json_path)
        row.definition = schema.model_dump(mode="json")
        row.created_by = schema.created_by
        row.proposal_run_id = proposal_run_id
        row.notes = schema.notes
        session.add(row)
    return yaml_path, json_path


@dataclass
class SchemaValidationResult:
    ok: bool
    schema_id: str | None = None
    errors: list[str] = field(default_factory=list)


def validate_schema_file(
    path: Path, *, activate: bool = False, engine: Engine | None = None
) -> SchemaValidationResult:
    errors: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return SchemaValidationResult(ok=False, errors=[f"cannot load YAML: {exc}"])

    try:
        schema = CorpusSchema.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        return SchemaValidationResult(ok=False, errors=[f"invalid corpus schema: {exc}"])

    generated = schema.to_json_schema()
    try:
        validator_for(generated).check_schema(generated)
    except SchemaError as exc:
        errors.append(f"generated JSON Schema is invalid: {exc.message}")

    undefined = [
        name
        for name in [*schema.base, *schema.extension_components()]
        if name not in schema.components
    ]
    if undefined:
        # Not fatal — components may be defined later — but reviewers must see it.
        errors.append(f"components referenced but not defined: {sorted(undefined)}")

    result = SchemaValidationResult(ok=not errors, schema_id=schema.schema_id, errors=errors)

    if result.ok and activate:
        if engine is None:
            from modelkb.db.init import init_db

            engine, _ = init_db(get_settings().database.url)
        with session_scope(engine) as session:
            row = session.get(m.SchemaVersion, schema.schema_id)
            if row is None:
                result.ok = False
                result.errors.append(
                    f"schema {schema.schema_id} is not registered; run propose-schema first"
                )
                return result
            for other in session.scalars(
                select(m.SchemaVersion).where(m.SchemaVersion.status == "active")
            ):
                other.status = "retired"
            row.status = "active"
    return result


def get_active_schema(engine: Engine) -> CorpusSchema | None:
    with session_scope(engine) as session:
        row = session.scalar(select(m.SchemaVersion).where(m.SchemaVersion.status == "active"))
        if row is None:
            return None
        return CorpusSchema.model_validate(row.definition)

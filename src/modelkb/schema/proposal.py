"""Pass A (LLM stage): propose a corpus schema from a discovery report.

The LLM sees the discovery report (per-document structural summaries), never
full page text. Its output is validated against ``SchemaProposal``, converted
into a ``CorpusSchema``, and persisted as reviewable YAML + JSON Schema. The
schema becomes binding only after human review + ``kb validate-schema
--activate``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import cast

from sqlalchemy.engine import Engine

from modelkb.core.config import get_settings
from modelkb.core.logging import get_logger
from modelkb.db import models as m
from modelkb.db.init import init_db
from modelkb.db.models.common import RunKind, RunStatus
from modelkb.db.session import session_scope
from modelkb.llm.base import LlmCall, LLMProvider
from modelkb.llm.provider import VllmProvider
from modelkb.llm.recorder import make_db_recorder
from modelkb.schema.models import SchemaProposal
from modelkb.schema.registry import next_schema_id, persist_schema

log = get_logger("schema.proposal")

PROMPT_VERSION = "schema_proposal_v1"


@dataclass(frozen=True)
class ProposalResult:
    schema_id: str
    yaml_path: Path
    json_path: Path
    run_id: str


def load_prompt() -> str:
    return resources.files("modelkb.llm.prompts").joinpath(f"{PROMPT_VERSION}.md").read_text()


def run_schema_proposal(
    *,
    discovery_run_id: str,
    provider: LLMProvider | None = None,
    engine: Engine | None = None,
) -> ProposalResult:
    settings = get_settings()
    if engine is None:
        engine, _ = init_db(settings.database.url)

    with session_scope(engine) as session:
        discovery_run = session.get(m.ExtractionRun, uuid.UUID(discovery_run_id))
        if discovery_run is None:
            raise ValueError(f"discovery run not found: {discovery_run_id}")
        report_path = Path(discovery_run.stats.get("report_path", ""))
        if not report_path.is_file():
            raise FileNotFoundError(
                f"discovery report missing for run {discovery_run_id}: {report_path}"
            )
        report = json.loads(report_path.read_text())
        schema_id = next_schema_id(session)

        run = m.ExtractionRun(
            kind=RunKind.schema_proposal,
            params={"discovery_run_id": discovery_run_id, "prompt_version": PROMPT_VERSION},
        )
        session.add(run)
        session.flush()
        run_id = run.id

    if provider is None:
        provider = VllmProvider(settings.vllm, recorder=make_db_recorder(engine))

    call = LlmCall(
        purpose="schema_proposal",
        prompt_version=PROMPT_VERSION,
        messages=[
            {"role": "system", "content": load_prompt()},
            {
                "role": "user",
                "content": "DISCOVERY REPORT (JSON):\n" + json.dumps(report, indent=2),
            },
        ],
        max_tokens=8192,
        extraction_run_id=run_id,
    )
    outcome = provider.complete_structured(call, SchemaProposal)
    proposal = cast(SchemaProposal, outcome.parsed)
    schema = proposal.to_corpus_schema(schema_id)
    schema.notes = (
        f"proposed from discovery run {discovery_run_id}; "
        f"llm attempts: {outcome.attempts}. " + (schema.notes or "")
    )

    yaml_path, json_path = persist_schema(schema, engine=engine, proposal_run_id=run_id)

    with session_scope(engine) as session:
        run_row = session.get(m.ExtractionRun, run_id)
        assert run_row is not None
        run_row.status = RunStatus.success
        run_row.schema_version_id = schema_id
        run_row.stats = {
            "schema_id": schema_id,
            "llm_attempts": outcome.attempts,
            "request_hash": outcome.request_hash,
            "response_hash": outcome.response_hash,
        }
        run_row.finished_at = datetime.now(UTC)

    log.info("schema proposed", schema_id=schema_id, yaml=str(yaml_path))
    return ProposalResult(
        schema_id=schema_id, yaml_path=yaml_path, json_path=json_path, run_id=str(run_id)
    )

"""Schema proposal workflow: discovery report → LLM proposal → persisted schema.

Uses a fake provider; the HTTP layer is covered by test_llm_provider.py.
"""

import json
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from modelkb.db import models as m
from modelkb.db.init import init_db
from modelkb.db.session import session_scope
from modelkb.discovery.service import run_discovery
from modelkb.llm.base import LlmCall, LlmOutcome
from modelkb.schema.models import (
    ProposedComponent,
    ProposedExtension,
    ProposedField,
    SchemaProposal,
)
from modelkb.schema.proposal import run_schema_proposal
from modelkb.schema.registry import validate_schema_file
from tests.fixtures.synthetic_pdfs import make_corpus


class FakeProvider:
    name = "fake"
    backend = "chat_only"

    def __init__(self, proposal: SchemaProposal) -> None:
        self._proposal = proposal
        self.calls: list[LlmCall] = []

    def complete_structured(self, call: LlmCall, response_model: type[BaseModel]) -> LlmOutcome:
        self.calls.append(call)
        return LlmOutcome(
            parsed=self._proposal,
            raw_text=self._proposal.model_dump_json(),
            request_hash="req",
            response_hash="resp",
            latency_ms=1,
            attempts=1,
        )


def _canned_proposal() -> SchemaProposal:
    return SchemaProposal(
        taxonomy=["macro_model", "housing_model", "pension_model", "interest_rate_risk_model"],
        base_components=[
            ProposedComponent(
                name=name,
                description=f"{name} component",
                fields=[
                    ProposedField(
                        name="title",
                        dtype="string",
                        required=(name == "document_metadata"),
                    )
                ],
            )
            for name in (
                "document_metadata",
                "model_identity",
                "model_version",
                "sections",
                "claims",
                "assumptions",
                "variables",
                "equations",
                "coefficients",
                "code_references",
                "citations",
                "relationships",
                "evidence",
            )
        ],
        extensions=[
            ProposedExtension(model_type="housing_model", components=["property_segments"]),
            ProposedExtension(
                model_type="interest_rate_risk_model",
                components=["curve_specification", "scenario_definition"],
            ),
        ],
        section_mappings={"methodology": ["Model methodology", "Overview"]},
        relationship_types=["depends_on", "provides_input_to", "produces", "consumes"],
        confidence_rules=["return null when version is not explicit on cover or header"],
        manual_review_cases=["conflicting version strings across pages"],
    )


@pytest.fixture()
def discovery(settings, tmp_path: Path):
    input_dir = tmp_path / "input"
    make_corpus(input_dir)
    engine, _ = init_db(settings.database.url)
    result = run_discovery(input_dir=input_dir, engine=engine)
    return engine, result


def test_proposal_persists_reviewable_artifacts(settings, discovery, tmp_path: Path) -> None:
    engine, result = discovery
    provider = FakeProvider(_canned_proposal())
    proposal = run_schema_proposal(discovery_run_id=result.run_id, provider=provider, engine=engine)

    assert proposal.schema_id == "corpus-schema-v1"
    assert proposal.yaml_path.is_file() and proposal.json_path.is_file()

    on_disk = yaml.safe_load(proposal.yaml_path.read_text())
    assert on_disk["extensions"]["interest_rate_risk_model"] == [
        "curve_specification",
        "scenario_definition",
    ]
    generated = json.loads(proposal.json_path.read_text())
    assert generated["$schema"].endswith("2020-12/schema")

    with session_scope(engine) as session:
        row = session.get(m.SchemaVersion, "corpus-schema-v1")
        assert row is not None and row.status == "proposed"
        assert row.proposal_run_id is not None

    # the LLM saw the discovery report, and the prompt is versioned
    sent = provider.calls[0]
    assert sent.prompt_version == "schema_proposal_v1"
    assert "DISCOVERY REPORT" in sent.messages[1]["content"]
    assert "macro_core.pdf" in sent.messages[1]["content"]


def test_schema_ids_increment(settings, discovery) -> None:
    engine, result = discovery
    first = run_schema_proposal(
        discovery_run_id=result.run_id, provider=FakeProvider(_canned_proposal()), engine=engine
    )
    second = run_schema_proposal(
        discovery_run_id=result.run_id, provider=FakeProvider(_canned_proposal()), engine=engine
    )
    assert (first.schema_id, second.schema_id) == ("corpus-schema-v1", "corpus-schema-v2")


def test_validate_schema_cli_path_and_activation(settings, discovery, tmp_path: Path) -> None:
    engine, result = discovery
    proposal = run_schema_proposal(
        discovery_run_id=result.run_id, provider=FakeProvider(_canned_proposal()), engine=engine
    )
    ok = validate_schema_file(proposal.yaml_path, engine=engine)
    assert ok.ok, ok.errors

    activated = validate_schema_file(proposal.yaml_path, activate=True, engine=engine)
    assert activated.ok
    with session_scope(engine) as session:
        row = session.get(m.SchemaVersion, proposal.schema_id)
        assert row.status == "active"


def test_validate_schema_rejects_broken_file(tmp_path: Path) -> None:
    bad = tmp_path / "corpus-schema-v9.yaml"
    bad.write_text("schema_id: corpus-schema-v9\nbase: [document_metadata]\n")
    result = validate_schema_file(bad)
    assert not result.ok
    assert any("baseline" in e for e in result.errors)

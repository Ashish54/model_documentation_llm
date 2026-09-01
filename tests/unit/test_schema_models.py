import pytest
from jsonschema.validators import validator_for
from pydantic import ValidationError

from modelkb.schema.models import (
    REQUIRED_BASE_COMPONENTS,
    ComponentSpec,
    CorpusSchema,
    ProposedComponent,
    SchemaProposal,
)


def _schema(**overrides) -> CorpusSchema:
    payload = {
        "schema_id": "corpus-schema-v1",
        "base": list(REQUIRED_BASE_COMPONENTS),
        "extensions": {"housing_model": ["property_segments", "geographic_granularity"]},
        "components": {
            name: ComponentSpec(name=name).model_dump() for name in REQUIRED_BASE_COMPONENTS
        },
        "relationship_vocabulary": ["depends_on", "provides_input_to"],
    }
    payload.update(overrides)
    return CorpusSchema.model_validate(payload)


def test_baseline_components_are_enforced() -> None:
    with pytest.raises(ValidationError, match="baseline components missing"):
        CorpusSchema(schema_id="corpus-schema-v1", base=["document_metadata"])


def test_generated_json_schema_is_valid() -> None:
    schema = _schema()
    generated = schema.to_json_schema()
    validator_for(generated).check_schema(generated)  # raises on invalid draft-2020-12
    assert generated["required"] == ["document_metadata", "model_identity", "evidence"]
    assert "property_segments" in generated["$defs"]


def test_extensions_are_additive() -> None:
    v1 = _schema()
    v2 = _schema(
        schema_id="corpus-schema-v2",
        extensions={
            "housing_model": ["property_segments", "geographic_granularity"],
            "pension_model": ["demographic_assumptions"],
        },
    )
    # baseline identical ⇒ records extracted under v1 stay valid under v2
    assert v1.base == v2.base
    assert set(v1.extension_components()) <= set(v2.extension_components())


def test_proposal_restores_baseline_the_llm_dropped() -> None:
    proposal = SchemaProposal(
        taxonomy=["macro", "housing"],
        base_components=[
            ProposedComponent(name="document_metadata"),
            ProposedComponent(name="model_identity"),
            # LLM "forgot" the other 11 baseline components
        ],
    )
    schema = proposal.to_corpus_schema("corpus-schema-v1")
    assert set(REQUIRED_BASE_COMPONENTS) <= set(schema.base)

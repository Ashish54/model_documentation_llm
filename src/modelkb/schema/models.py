"""Corpus schema artifacts: the versioned extraction contract.

Two artifact shapes live here:
* ``CorpusSchema``   — the persisted, reviewable schema (YAML + JSON Schema on
  disk, row in schema_version). Baseline components are stable; extensions are
  additive and never invalidate records extracted under older schemas.
* ``SchemaProposal`` — the LLM's structured output in Pass A, which a human
  reviews and edits before it becomes a CorpusSchema.

Neither is embedded in Python code: code only defines the *shape*; the actual
schema content is data, reviewed and versioned as an artifact (ADR 0003).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

#: Baseline components every corpus schema must include (spec-mandated).
REQUIRED_BASE_COMPONENTS: tuple[str, ...] = (
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

SCHEMA_ID_PATTERN = r"^corpus-schema-v\d+$"


class SchemaFieldSpec(BaseModel):
    name: str
    dtype: str = "string"  # string|number|integer|date|boolean|enum|array|object
    required: bool = False
    enum: list[str] | None = None
    description: str | None = None


class ComponentSpec(BaseModel):
    name: str
    description: str | None = None
    fields: list[SchemaFieldSpec] = Field(default_factory=list)


class CorpusSchema(BaseModel):
    schema_id: str = Field(pattern=SCHEMA_ID_PATTERN)
    status: str = "proposed"  # proposed | active | retired
    created_by: str = "llm"  # llm | human
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    base: list[str]
    extensions: dict[str, list[str]] = Field(default_factory=dict)
    components: dict[str, ComponentSpec] = Field(default_factory=dict)
    relationship_vocabulary: list[str] = Field(default_factory=list)
    section_mappings: dict[str, list[str]] = Field(default_factory=dict)
    confidence_rules: list[str] = Field(default_factory=list)
    manual_review_cases: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _base_is_superset(self) -> CorpusSchema:
        missing = set(REQUIRED_BASE_COMPONENTS) - set(self.base)
        if missing:
            raise ValueError(f"baseline components missing: {sorted(missing)}")
        return self

    def extension_components(self) -> list[str]:
        return [c for comps in self.extensions.values() for c in comps]

    def to_json_schema(self) -> dict[str, Any]:
        """Draft 2020-12 JSON Schema for one extraction record.

        Components become $defs; the root requires the core identity/evidence
        components and stays open (additionalProperties) so extensions and
        future components never invalidate older records.
        """
        defs: dict[str, dict[str, Any]] = {}
        for name in [*self.base, *self.extension_components()]:
            spec = self.components.get(name)
            properties: dict[str, dict[str, Any]] = {}
            required: list[str] = []
            if spec:
                for f in spec.fields:
                    field_schema: dict[str, Any] = {"type": _json_type(f.dtype)}
                    if f.enum:
                        field_schema["enum"] = f.enum
                    if f.description:
                        field_schema["description"] = f.description
                    properties[f.name] = field_schema
                    if f.required:
                        required.append(f.name)
            defs[name] = {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": True,
            }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://modelkb.local/schemas/{self.schema_id}.json",
            "title": self.schema_id,
            "type": "object",
            "$defs": defs,
            "properties": {name: {"$ref": f"#/$defs/{name}"} for name in self.base},
            "required": ["document_metadata", "model_identity", "evidence"],
            "additionalProperties": True,
        }


def _json_type(dtype: str) -> str | list[str]:
    return {
        "string": "string",
        "number": "number",
        "integer": "integer",
        "date": "string",
        "boolean": "boolean",
        "enum": "string",
        "array": "array",
        "object": "object",
    }.get(dtype, "string")


# --- LLM proposal output (Pass A) -------------------------------------------- #


class ProposedField(BaseModel):
    name: str
    dtype: str = "string"
    required: bool = False
    enum: list[str] | None = None
    description: str | None = None


class ProposedComponent(BaseModel):
    name: str
    description: str | None = None
    fields: list[ProposedField] = Field(default_factory=list)
    rationale: str | None = None


class ProposedExtension(BaseModel):
    model_type: str  # e.g. housing_model, interest_rate_risk_model, pension_model
    components: list[str] = Field(default_factory=list)
    rationale: str | None = None


class SchemaProposal(BaseModel):
    """What the LLM returns in Pass A. Everything here is a *proposal* — it
    becomes binding only after human review and validate-schema activation."""

    taxonomy: list[str] = Field(default_factory=list)
    base_components: list[ProposedComponent]
    extensions: list[ProposedExtension] = Field(default_factory=list)
    section_mappings: dict[str, list[str]] = Field(default_factory=dict)
    relationship_types: list[str] = Field(default_factory=list)
    confidence_rules: list[str] = Field(default_factory=list)
    manual_review_cases: list[str] = Field(default_factory=list)
    notes: str | None = None

    def to_corpus_schema(self, schema_id: str) -> CorpusSchema:
        base = [c.name for c in self.base_components]
        missing = set(REQUIRED_BASE_COMPONENTS) - set(base)
        for name in sorted(missing):
            # Never let the LLM shrink the baseline; add and flag for review.
            self.base_components.append(
                ProposedComponent(
                    name=name,
                    description="baseline component added by pipeline (LLM omitted it)",
                    rationale="required baseline",
                )
            )
            base.append(name)
        components = {
            c.name: ComponentSpec(
                name=c.name,
                description=c.description,
                fields=[SchemaFieldSpec(**f.model_dump()) for f in c.fields],
            )
            for c in self.base_components
        }
        # Extension components get placeholder definitions so the schema
        # artifact is self-contained; reviewers flesh them out, extraction
        # tolerates empty definitions (additionalProperties everywhere).
        for extension in self.extensions:
            for name in extension.components:
                components.setdefault(
                    name,
                    ComponentSpec(
                        name=name,
                        description=(
                            f"extension component for {extension.model_type} — "
                            "placeholder, define during schema review"
                        ),
                    ),
                )
        return CorpusSchema(
            schema_id=schema_id,
            created_by="llm",
            base=base,
            extensions={e.model_type: e.components for e in self.extensions},
            components=components,
            relationship_vocabulary=self.relationship_types,
            section_mappings=self.section_mappings,
            confidence_rules=self.confidence_rules,
            manual_review_cases=self.manual_review_cases,
            notes=self.notes,
        )

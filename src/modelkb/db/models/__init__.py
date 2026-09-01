"""ORM models. Importing this package registers every table on Base.metadata."""

from modelkb.db.models.code import CodeReference, CodeSymbol
from modelkb.db.models.extraction import ExtractionRun, LlmInteraction, SchemaVersion
from modelkb.db.models.knowledge import (
    Assumption,
    Claim,
    ClaimVersion,
    Coefficient,
    Equation,
    Model,
    ModelVersion,
    Variable,
)
from modelkb.db.models.relationship import Relationship
from modelkb.db.models.review import ReviewState
from modelkb.db.models.source import (
    Artifact,
    ArtifactVersion,
    ChangeEvent,
    Document,
    DocumentVersion,
    ModelInfoSnapshot,
    Page,
    Section,
    SourceLocator,
)

__all__ = [
    "Artifact",
    "ArtifactVersion",
    "Assumption",
    "ChangeEvent",
    "Claim",
    "ClaimVersion",
    "CodeReference",
    "CodeSymbol",
    "Coefficient",
    "Document",
    "DocumentVersion",
    "Equation",
    "ExtractionRun",
    "LlmInteraction",
    "Model",
    "ModelInfoSnapshot",
    "ModelVersion",
    "Page",
    "Relationship",
    "ReviewState",
    "SchemaVersion",
    "Section",
    "SourceLocator",
    "Variable",
]

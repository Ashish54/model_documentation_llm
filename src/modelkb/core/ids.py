"""Stable, readable identifier helpers.

Readable IDs (``model:swiss_hpi``, ``variable:macro.policy_rate``) are the
primary identifiers of the knowledge base. Database surrogate keys exist for
join efficiency but are never the only identifier of a record.

Deterministic IDs (evidence, extraction packages) are derived from content
hashes so re-ingestion is idempotent: the same evidence yields the same ID.
"""

from __future__ import annotations

import hashlib
import re
import uuid

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 64) -> str:
    slug = _SLUG_RE.sub("_", text.strip().lower()).strip("_")
    return slug[:max_len] or "unnamed"


def short_hash(data: str | bytes, *, length: int = 16) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()[:length]


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# --- Readable ID constructors -------------------------------------------------


def model_ref(slug: str) -> str:
    return f"model:{slug}"


def model_version_ref(slug: str, version: str) -> str:
    return f"modelver:{slug}:{slugify(version)}"


def document_ref(slug: str) -> str:
    return f"document:{slug}"


def document_version_ref(slug: str, version: str) -> str:
    return f"docver:{slug}:{slugify(version)}"


def assumption_ref(model_slug: str, name: str) -> str:
    return f"assumption:{model_slug}.{slugify(name)}"


def variable_ref(scope: str, name: str) -> str:
    return f"variable:{scope}.{slugify(name)}"


def equation_ref(model_slug: str, label: str) -> str:
    return f"equation:{model_slug}.{slugify(label)}"


def coefficient_ref(model_slug: str, name: str) -> str:
    return f"coefficient:{model_slug}.{slugify(name)}"


def code_symbol_ref(git_commit: str, path: str, qualname: str) -> str:
    return f"code:{git_commit[:12]}:{path}#{qualname}"


def evidence_id(
    artifact_sha256: str,
    *,
    kind: str,
    page: int | None,
    text_start: int | None = None,
    text_end: int | None = None,
    extracted_text_hash: str | None = None,
    table_label: str | None = None,
    equation_label: str | None = None,
) -> str:
    """Deterministic evidence ID — identical locators dedupe automatically."""
    canonical = "|".join(
        str(part)
        for part in (
            artifact_sha256,
            kind,
            page,
            text_start,
            text_end,
            extracted_text_hash,
            table_label,
            equation_label,
        )
    )
    return f"evidence:{short_hash(canonical)}"

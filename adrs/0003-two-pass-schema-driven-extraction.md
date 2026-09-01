# ADR 0003: Two-pass, schema-driven extraction

## Status

Accepted (milestones 2–3)

## Context

The 28 PDFs must not be assumed structurally identical. Committing to a rigid
extraction schema before seeing the corpus would bake in wrong assumptions.

## Decision

* **Pass A (deterministic discovery).** Every PDF is archived and parsed with
  PyMuPDF: pages, headings (TOC → numbered regex → font heuristics, detection
  method recorded), tables (+captions), equation-like blocks, citations,
  code references, metadata candidates, quality/warnings. Output: an
  extraction package per artifact (`extractions/<sha>/`) and a corpus-wide
  discovery report. No LLM involved.
* **Pass A (LLM schema proposal).** The LLM sees only the discovery report
  (structural summaries), proposes taxonomy, baseline components, per-type
  extensions, section mappings, relationship types, confidence and review
  rules. Output is validated against `SchemaProposal` and persisted as
  **reviewable artifacts**: `knowledge/schema/corpus-schema-vN.yaml` (human
  source of truth), `.json` (generated JSON Schema contract), and a
  `schema_version` row (proposed → active → retired).
* **Pass B (schema-guided extraction, milestone 4).** Deterministic parsing
  first; the LLM only for classification/normalization/semantic extraction,
  with outputs validated against the active schema.
* **Baseline stability.** `REQUIRED_BASE_COMPONENTS` are enforced in code;
  a proposal that drops them gets them re-added with a review flag.
  Extensions are additive; new schema versions never invalidate records
  extracted under older ones (every derived row carries `schema_version_id`).

## Consequences

* The schema is data, reviewed like any other artifact — not buried in code.
* Discovery is a first-class product feature: its report tells governance
  whether the corpus is uniform before extraction is committed to.
* Prompts are versioned files (`llm/prompts/schema_proposal_v1.md`), and the
  prompt version is stored with every LLM interaction.

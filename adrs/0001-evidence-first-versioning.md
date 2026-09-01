# ADR 0001: Evidence-first storage and versioning

## Status

Accepted (milestones 1–3)

## Context

The knowledge base feeds governed financial models. Every derived record must
be re-traceable to exact source evidence, SharePoint has no usable version
history, and all future artifact versions must be preserved after initial
ingestion.

## Decision

* **Immutable artifact store.** Original files are copied into
  `archive/<sha256[:2]>/<sha256>` and made read-only. Content addressing makes
  ingestion idempotent; re-archiving identical bytes is a no-op.
* **Versioning patterns.**
  * Identity + version tables for entities with stable identity:
    `artifact`/`artifact_version`, `document`/`document_version`,
    `model`/`model_version`, `claim`/`claim_version`.
  * Append-only versioned rows for leaf concepts (`assumption`, `variable`,
    `equation`, `coefficient`): same readable `ref`, new row, old row gets
    `is_current=false`. Chosen over per-entity version tables to avoid
    doubling the schema for concepts that change atomically.
* **No destructive updates.** Corrections are new versions. Currency is
  expressed by `is_current` flags, never by rewriting.
* **Two clocks.** `recorded_at` (system time, server default) is on every
  table; `valid_from`/`source_modified_at` capture source time where known.
* **Deterministic evidence IDs.** `source_locator.id =
  evidence:<sha256(canonical locator)[:16]>` — identical evidence dedupes
  across re-ingestion instead of duplicating.
* **Incomplete locators are allowed.** Parsers record the strongest evidence
  available and log gaps in `extraction_limitations` / quality warnings
  (e.g. scanned pages).

## Consequences

* Re-ingestion is safe and cheap (content-addressed skips).
* Any historical extraction can be rebuilt: archived bytes + recorded parser
  name/version + settings hash in the extraction package manifest.
* Storage grows monotonically — accepted; evidence retention outranks
  compactness in a governed system.

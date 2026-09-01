# ADR 0002: Relational graph with precedence-based conflict resolution

## Status

Accepted (schema in milestone 1; resolver lands in milestone 5)

## Context

Models are interconnected. `model_info.json` describes connections but the
PDFs are authoritative and may override or add relationships. Conflicts must
be retained and marked, never silently deleted. No graph database is wanted.

## Decision

* **One `relationship` table** with string refs (`subject_ref`, `predicate`,
  `object_ref`) instead of FKs, so `model_info.json` can assert edges about
  models the PDFs have not yet established. Referential completeness is a
  validation concern (milestone 8), not a storage constraint.
* **Assertion metadata on every edge:** `asserted_by`
  (pdf|model_info_json|human), `source_precedence` (config:
  human=100 > pdf=20 > model_info_json=10), `confidence`, `status`
  (proposed|active|superseded|disputed), `valid_from`, and
  `relationship_evidence` links to source locators.
* **Conflicts coexist.** A PDF assertion that contradicts a
  `model_info.json` assertion is inserted alongside it; a `change_event` of
  kind `relationship_conflict` records the dispute. Nothing is deleted.
* **Deterministic resolver for the "current view":** for each
  (subject, predicate) group, order active assertions by
  (source_precedence desc, confidence desc, recorded_at desc) and take the
  first. The resolver is pure SQL/Python over the table — same input, same
  view — while the full trail remains queryable.
* **Indexes for future recursive traversal** (PostgreSQL recursive CTEs):
  `ix_relationship_forward (subject_ref, predicate, status)` and
  `ix_relationship_reverse (object_ref, predicate, status)`.
* **Extensible vocabulary.** Initial predicates are fixed in
  `EDGE_VOCABULARY`; new predicates are added via the active corpus schema
  YAML (never renamed/removed), keeping old edges interpretable.

## Consequences

* The graph supports audit questions ("who asserted this edge, on what
  evidence, and why is it the current one?") with plain SQL.
* model_info.json is treated as an evidence-bearing source, not truth:
  it is archived (artifact) and snapshotted (`model_info_snapshot`) like
  any other input.

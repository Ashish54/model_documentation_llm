# Implementation Plan — modelkb

Audience: the coding agent continuing this build. Read
`docs/Copilot_instructions.md` first for the invariants and gotchas; this file
is the *what's left*, milestone by milestone, with completion criteria.

Quality gates (must stay green after every milestone):

```bash
.venv/bin/python -m pytest tests/     # all pass
.venv/bin/ruff check src tests        # clean
.venv/bin/ruff format --check src tests
.venv/bin/mypy                        # strict, clean
```

## Status

| # | Milestone | Status | Proof |
|---|-----------|--------|-------|
| 1 | Skeleton, config, 31-table DB, immutable archive, source adapters, CLI | ✅ done | `tests/integration/test_migration.py`, `test_archive.py` |
| 2 | Deterministic PDF parse, extraction packages, corpus discovery | ✅ done | `test_pymupdf_parser.py`, `test_discovery.py` |
| 3 | Schema proposal workflow, schema registry, LLM provider + audit | ✅ done | `test_schema_proposal.py`, `test_llm_provider.py` |
| 4 | Pass B: schema-guided semantic extraction | ⬜ next | tests #1, #5 below |
| 5 | `model_info.json` ingestion, relationship conflict resolver | ⬜ | test #2 |
| 6 | Git-tag code inventory, code-reference linker | ⬜ | test #4 |
| 7 | Markdown/YAML knowledge artifact generation | ⬜ | test #7 |
| 8 | Full validation suite, FastAPI inspection service, docs polish | ⬜ | spec §CLI and API |

Required tests (spec §Quality) already covered: #3 (artifact versioning,
`test_discovery.py::test_changed_content_adds_version_and_preserves_prior`)
and #6 (provider level, `test_llm_provider.py`).

---

## Milestone 4 — Pass B: schema-guided semantic extraction

Goal: after a schema is active, extract assumptions/variables/equations/
coefficients/claims/relationships from every PDF, each with evidence locators.

Planned modules:

* `src/modelkb/extraction/semantic.py` — orchestrates per-document Pass B:
  load extraction package + active `CorpusSchema` → deterministic candidates
  (tables, equations, metadata) → LLM classification/extraction per section →
  validate → persist with evidence links.
* `src/modelkb/extraction/prompts/` — versioned prompt templates
  (`semantic_extract_v1.md`). Prompts receive precise source spans and the
  evidence IDs minted in Pass A; the LLM must cite those IDs.
* `src/modelkb/extraction/persist.py` — writes `claim`/`claim_version`,
  `assumption`, `variable`, `equation`, `coefficient` rows + evidence
  association rows; detects document identity/version from content (PDFs are
  authoritative) and supersedes provisional discovery-time values.

Rules that are hard requirements, not guidelines:

* Monetary values, coefficients, formulas, dates, model versions: deterministic
  extraction first; LLM output must be validated against the source span
  (exact substring / numeric match) before persisting.
* LLM returns `null` for absent fields, a `reasoning_category`
  (`explicit|inferred_from_text|ambiguous`), and ≥1 evidence ID per populated
  substantive field. Persist these on every row.
* Wire CLI `ingest-pdfs --input … --schema <version>` (stub exists in
  `cli.py`).

Completion criteria:

1. Test #1 passes: query every current assumption/variable/equation/
   coefficient/claim_version and assert ≥1 evidence association each
   (`kb validate-ingestion` may be the harness).
2. Test #5 passes: activate a schema v2 that adds an extension component,
   re-extract one document, and assert all v1-extracted rows remain valid
   (baseline unchanged, old `schema_version_id` intact).
3. End-to-end on the synthetic corpus with a fake provider: rows exist for
   all four documents; `ambiguous` fields carry nulls, never invented values.

## Milestone 5 — model_info.json + relationship conflicts

Planned modules:

* `src/modelkb/relationships/ingest_model_info.py` — archive the JSON as an
  artifact (`ArtifactKind.json`), snapshot into `model_info_snapshot`, mint
  `relationship` rows (`asserted_by=model_info_json`, precedence from config).
* `src/modelkb/relationships/resolver.py` — deterministic current-view
  resolver per ADR 0002: group by (subject_ref, predicate), order by
  (source_precedence, confidence, recorded_at) desc, first wins; mark
  `is_current_view`; write `change_event(kind="relationship_conflict")` when
  lower-precedence assertions lose.
* Wire CLI `ingest-model-info --path model_info.json`.

Completion criteria:

1. Test #2 passes: a PDF-asserted relationship that contradicts a
   model_info.json assertion leaves **both** rows in the table; the resolver
   returns the PDF one as current; a conflict change_event exists; nothing is
   deleted.
2. Fixture: `tests/fixtures/model_info.json` (4 models, 3 edges, 1 conflict
   with a PDF assertion).

## Milestone 6 — code inventory + linker

Planned modules:

* `src/modelkb/codebase/inventory.py` — resolve configured repo (local path or
  clone `repo_url` to `code.workdir`), `git checkout <tag>` read-only, record
  tag + exact commit; walk `*.py` with `ast`: packages, modules, classes,
  functions, methods, imports, docstrings, constants → `code_symbol` rows
  (stable ref `code:<commit12>:<path>#<qualname>`). Never execute model code.
* `src/modelkb/codebase/linker.py` — map `code_reference` rows to symbols:
  exact path+symbol → resolved; multiple candidates → ambiguous (record all
  candidate IDs); none → unresolved/obsolete. Never guess.
* Wire CLI `inventory-code`, `link-code-references`.

Completion criteria:

1. Test #4 passes: a synthetic ambiguous reference (two same-named functions
   in different modules) stays `ambiguous` with both candidates recorded.
2. Fixture: tiny git repo in `tests/fixtures/` built at test time with two
   tags; inventory runs against the configured tag only.

## Milestone 7 — Markdown/YAML artifact generation

Planned modules:

* `src/modelkb/knowledge/render.py` — render `knowledge/models/<model-id>/`
  trees: `model.md`, `assumptions/*.md`, `variables/`, `equations/` with YAML
  frontmatter per spec (type, id, model_id, document_version_id, status,
  trust, schema_version, sources with evidence locators, code_references)
  and body sections (Statement / Rationale / Ambiguities).
* Wire CLI `generate-knowledge-artifacts`.

Completion criteria:

1. Test #7 passes: parse every generated file's frontmatter and assert each
   `sources[].evidence_id` exists in `source_locator`.
2. Every artifact carries stable ID, schema version, confidence, review
   state, links to connected models, and an Ambiguities section when
   `reasoning_category=ambiguous` fields exist.

## Milestone 8 — validation suite + inspection API

Planned modules:

* `src/modelkb/validation/suite.py` — evidence completeness (#1), referential
  completeness of relationship endpoints (warn, not fail), schema-version
  consistency, orphan detection. Wire `kb validate-ingestion`.
* `src/modelkb/api/app.py` — FastAPI read-only inspection service with the
  spec's routes (`/health`, `/artifacts`, `/documents`, `/models`,
  `/models/{id}`, `/models/{id}/relationships`, `/evidence/{id}`,
  `/extraction-runs/{id}`, `/schemas`, `/conflicts`). OpenAPI docs come free
  from FastAPI. No chat, no Q&A endpoints.

Completion criteria: all spec routes respond against a seeded test database;
`kb validate-ingestion` fails loudly when evidence is missing.

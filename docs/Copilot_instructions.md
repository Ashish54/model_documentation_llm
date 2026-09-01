# Copilot Instructions — modelkb

Everything a coding agent must know to work in this repository safely. For
milestone work, read `docs/implementation_plan.md`. For rationale, read the
ADRs in `adrs/`. This file holds the invariants and the gotchas no config
confesses.

## Ground rules (violations are bugs, not style issues)

1. **Evidence is append-only.** Never `UPDATE` or `DELETE` rows in
   `artifact_version`, `source_locator`, `extraction_run`, `llm_interaction`,
   or any prior version row. Corrections are new rows; currency moves via
   `is_current` flags.
2. **Every substantive record carries evidence.** Assumptions, variables,
   equations, coefficients, claim versions, relationships, and code
   references link to `source_locator` through their `*_evidence`
   association tables. A row without evidence fails the validation suite.
3. **Deterministic first, LLM second.** Parse with code; use the LLM only for
   classification, normalization, and semantic extraction — and only through
   `LLMProvider.complete_structured` with a versioned prompt file. LLM
   outputs get Pydantic validation, `null` for absent fields, a
   `reasoning_category`, and evidence IDs per populated field.
4. **PDFs outrank model_info.json.** Conflicting relationship assertions
   coexist; resolution is the deterministic precedence resolver
   (ADR 0002), never deletion.
5. **Never execute model-library code.** The code inventory is AST-only.

## Quality gates — run all four before declaring done

```bash
.venv/bin/python -m pytest tests/
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy            # strict mode; keep it clean
```

## Repository map

| Path | Purpose |
|---|---|
| `src/modelkb/core/` | typed config (`config.py`), stable-ID helpers (`ids.py`), hashing, structured logging |
| `src/modelkb/db/` | ORM (`models/`), Alembic bootstrap (`init.py`), `JSONBCompat` (`types.py`) |
| `src/modelkb/archive/` | immutable sha256-addressed artifact store |
| `src/modelkb/sources/` | `DocumentSource` interface, local folder impl, SharePoint scaffold |
| `src/modelkb/pdf/` | parser output models, PyMuPDF parser, deterministic diff primitives |
| `src/modelkb/extraction/` | extraction-package writer (Pass B joins here in M4) |
| `src/modelkb/discovery/` | Pass A service + report schemas |
| `src/modelkb/schema/` | `CorpusSchema`/`SchemaProposal`, registry, proposal flow |
| `src/modelkb/llm/` | provider (direct + chat_only backends), JSON emulation, prompts, DB recorder |
| `alembic/` | one initial migration creating all 31 tables |
| `tests/fixtures/` | synthetic corpus generator (4 deliberately non-uniform PDFs) |

## Conventions

* **Readable IDs are primary identifiers** (`model:swiss_hpi`,
  `variable:macro.policy_rate`, `evidence:<hash16>`); build them with
  `core/ids.py` helpers, never f-strings scattered through code. Surrogate
  UUIDs exist for joins but are never the only identifier.
* **Deterministic evidence IDs**: `evidence_id(...)` hashes the canonical
  locator, so re-ingestion dedupes instead of duplicating. Keep the ID inputs
  stable; adding a field to the hash orphans existing rows.
* **Versioning patterns** (ADR 0001): identity+version tables for stable
  entities; append-only versioned rows (`ref` + `is_current`) for leaf
  concepts. Follow the existing pattern when adding entities.
* **Config**: add settings to the typed sub-models in `core/config.py`;
  YAML key and `KB_<SECTION>__<FIELD>` env var come free. Keep secrets in
  `.env` only.
* **Prompts** are versioned files in `llm/prompts/`; bump the version suffix
  on any semantic change and record the new constant where the prompt is
  used.

## Gotchas (learned the hard way — do not rediscover)

* **Alembic autogenerate** does not import `modelkb.db.types`; the
  `alembic/script.py.mako` template already includes it. Keep that line when
  editing the template, and verify new migrations run `upgrade`+`downgrade`
  on SQLite before committing.
* **FK cycles** between new tables break PostgreSQL creation order: mark one
  side `ForeignKey(..., use_alter=True, name=...)` (see
  `SchemaVersion.proposal_run_id`).
* **UUID primary keys on SQLite**: `session.get(Model, id_string)` raises —
  pass `uuid.UUID(id_string)`.
* **pymupdf is partially typed**: the mypy override for
  `modelkb.pdf.*` sets `disallow_untyped_calls = false`; iterate documents
  with `doc.load_page(i)` + `page: Any`, not `enumerate(doc)`.
* **pydantic-settings**: `Settings(_yaml_file=...)` silently does nothing
  with a customised YAML source — point at config files with the
  `KB_CONFIG_YAML` env var. The settings field is `schema_` (aliased to the
  `schema` YAML key) because `BaseSettings.schema()` exists.
* **Equation false positives**: code references contain math-ish characters;
  `_extract_equations` skips blocks matching any code-reference pattern.
  Preserve that ordering when editing the parser.
* **Doc-version identity**: identical version labels across revised editions
  are distinct rows (`(document_id, artifact_version_id)` unique; refs get a
  `-r<sha8>` suffix). Do not "simplify" this — PDFs are authoritative.
* **Batch extraction**: wrap per-document work in `session.begin_nested()`
  savepoints; one malformed document must not poison the batch.

## Definition of done for any change

1. All four quality gates pass.
2. New LLM usage records `llm_interaction` rows (use `make_db_recorder`).
3. New persisted knowledge has evidence links and a passing validation path.
4. Docs touched: update `docs/implementation_plan.md` status and add an ADR
   for any decision a future agent would otherwise re-litigate.

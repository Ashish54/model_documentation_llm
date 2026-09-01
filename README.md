# modelkb — Governed Financial-Model Knowledge Base Ingestion

Evidence-first, versioned ingestion of 28 interconnected financial-model
documentation PDFs, `model_info.json`, and a monolithic Python model library —
into PostgreSQL, with reviewable Markdown/YAML knowledge artifacts.

This is **not** a generic RAG app. It is a reliable evidence and extraction
layer designed so that retrieval, graph reasoning, semantic diffs, human
approval workflows, and quantitative execution can be built on top later.

> **Milestone status: 1–3 of 8 complete** (skeleton/DB/archive, deterministic
> PDF extraction + corpus discovery, schema-proposal workflow). See
> [Milestones](#milestones) for what remains.

## Architecture at a glance

```text
                 ┌──────────────────── Pass A ────────────────────┐
 PDFs ──▶ local mirror ─▶ immutable archive (sha256) ─▶ deterministic parse
 (SharePoint later)        var/archive/<sha>            (PyMuPDF: pages,
                                                          headings, tables,
                                                          equations, citations,
                                                          code refs, quality)
                                                            │
                              extractions/<sha>/{pages.jsonl, sections.json,
                                                 tables.json, equations.json,
                                                 citations.json,
                                                 code_references.json,
                                                 quality_report.json,
                                                 manifest.json}
                                                            │
                                            discovery report (all docs)
                                                            │
                                              vLLM (structured JSON)
                                                            │
                              knowledge/schema/corpus-schema-vN.{yaml,json}
                                            │  review + activate
                 ┌──────────────────── Pass B (milestone 4) ───────┐
                 ▼
 PostgreSQL ◀── schema-guided extraction with evidence locators
 (31 tables: artifact(_version), document(_version), page, section,
  source_locator, extraction_run, schema_version, llm_interaction,
  model(_version), claim(_version), assumption, variable, equation,
  coefficient, code_reference, code_symbol, relationship(+evidence),
  model_info_snapshot, change_event, review_state)
```

Ground rules enforced by the data model (ADR 0001):

* **Never overwrite evidence.** Artifacts are content-addressed and read-only;
  versions are append-only; `is_current` flags move, history stays.
* **Every substantive record has evidence.** `source_locator` rows carry page,
  section path, bounding box, text span, table/equation labels, and text
  hashes; many-to-many links to claims/assumptions/variables/equations/
  coefficients/relationships/code references.
* **The LLM never invents.** Structured outputs only (Pydantic-validated);
  `null` for absent fields; reasoning category (`explicit`,
  `inferred_from_text`, `ambiguous`) plus evidence IDs per populated field.
  Every LLM call is audited in `llm_interaction` (ADR 0004).
* **PDFs outrank model_info.json.** Conflicting relationship assertions are
  retained and marked; a deterministic resolver picks the current view by
  precedence (ADR 0002).

## Local setup

```bash
cd model-docs-wiki
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cp .env.example .env          # fill in vLLM endpoint + model, code repo, git tag
# Optional: point at a different YAML config via KB_CONFIG_YAML

.venv/bin/kb db-init          # apply Alembic migrations (SQLite default)
```

Database: SQLite is the zero-install default for dev/tests. For real
environments set PostgreSQL:

```bash
KB_DATABASE__URL=postgresql+psycopg://modelkb:CHANGE_ME@localhost:5432/modelkb
pip install psycopg[binary]   # driver for the PG DSN
```

All Postgres-specific design (JSONB via `JSONBCompat`, relationship traversal
indexes) activates automatically on a PG DSN; the test-suite runs on SQLite.

## End-to-end runbook (current milestones)

```bash
# 0. Put PDFs in the local mirror (SharePoint adapter is a scaffold for now)
cp /path/to/pdfs/*.pdf var/input/

# 1. Pass A — deterministic corpus discovery (archive + parse + report)
.venv/bin/kb discover-corpus --input var/input
#    → var/archive/<sha256>           immutable evidence copies
#    → var/extractions/<sha256>/      machine-readable extraction packages
#    → var/extractions/discovery/<run>/discovery_report.json
#    Idempotent: unchanged content is skipped; changed content adds a new
#    artifact_version and keeps the old one.

# 2. Pass A — LLM schema proposal (requires a reachable vLLM endpoint)
.venv/bin/kb propose-schema --discovery-run <run-id-from-step-1>
#    → knowledge/schema/corpus-schema-v1.yaml  (review this!)
#    → knowledge/schema/corpus-schema-v1.json  (JSON Schema contract)
#    → schema_version row (status=proposed), llm_interaction audit rows

# 3. Review the YAML, edit if needed, then validate + activate
.venv/bin/kb validate-schema --schema knowledge/schema/corpus-schema-v1.yaml --activate

# 4. Inspect state
.venv/bin/kb report
```

Without a live vLLM endpoint, steps 1/3/4 work fully; step 2 needs the
endpoint (or use the test-suite's fake provider as a template).

## Configuration

Typed config via pydantic-settings: `config/settings.yaml` < `.env` <
process env (`KB_<SECTION>__<FIELD>`). See `config/settings.yaml` and
`.env.example` for every key: input dir, archive/extractions/knowledge dirs,
DB URL, vLLM (`backend: chat_only|direct`, base URL, model — no API key needed
today; auth plugs into `VllmProvider._headers()` later), code repo + Git tag,
SharePoint scaffold, parser patterns, precedence values.

## Testing and quality gates

```bash
.venv/bin/python -m pytest tests/     # 45 tests: unit + integration (SQLite)
.venv/bin/ruff check src tests        # lint
.venv/bin/ruff format --check src tests
.venv/bin/mypy                        # strict type checking
```

Synthetic fixtures (`tests/fixtures/synthetic_pdfs.py`) generate four
*deliberately non-uniform* PDFs (TOC vs font headings, gridded tables,
equation labels, scanned-page simulation, code references) plus a sample
`model_info.json` (milestone 5) and a tiny Git repo fixture (milestone 6).
Real inputs drop in via config without code changes.

Notable tests already enforced (spec §Quality):

* prior artifact versions are preserved on re-ingestion (#3, artifact level);
* invalid LLM structured output is rejected and recorded (#6, provider level).

The remaining required tests land with their milestones (#1/#7 in M4/M7, #2 in
M5, #4 in M6, #5 in M4 schema-evolution tests).

## Project layout

```text
src/modelkb/
  core/        config (typed, YAML+env), structured logging, IDs, hashing
  db/          SQLAlchemy models, Alembic bootstrap, JSONBCompat
  archive/     immutable sha256-addressed artifact store
  sources/     DocumentSource interface, local folder, SharePoint scaffold
  pdf/         parser protocol models, PyMuPDF parser, diff primitives
  extraction/  extraction-package writer (extractions/<sha>/)
  discovery/   Pass A service + report schemas
  schema/      CorpusSchema/SchemaProposal models, registry, proposal flow
  llm/         provider abstraction, vLLM (direct + chat_only), JSON emulation,
               prompt templates (versioned), DB recorder
  cli.py       kb command line
alembic/       migrations (initial: full 31-table evidence model)
tests/         unit + integration, synthetic fixtures
adrs/          architecture decision records
docs/          audience-specific docs — start at docs/readme.md
.github/       Copilot instructions + project-specific agent skills
```

## Milestones

| # | Scope | Status |
|---|-------|--------|
| 1 | Skeleton, config, DB (31 tables), immutable archive, source adapters, CLI | ✅ done |
| 2 | Deterministic PDF extraction, extraction packages, corpus discovery report | ✅ done |
| 3 | Schema-proposal workflow, schema persistence/validation, LLM audit | ✅ done |
| 4 | Pass B schema-guided semantic extraction (evidence-required tests #1, #5) | pending |
| 5 | `model_info.json` ingestion, relationship conflicts/resolver (test #2) | pending |
| 6 | Git-tag code inventory, code-reference linker (test #4) | pending |
| 7 | Markdown/YAML knowledge artifact generation (test #7) | pending |
| 8 | Full validation suite, FastAPI inspection service, final docs | pending |

CLI interfaces for milestones 4–8 already exist and fail with explicit
"scheduled for milestone N" messages.

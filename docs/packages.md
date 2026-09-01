# packages.md — Recreating `pyproject.toml`

Instructions for an agent asked to recreate or audit the project's packaging.
The authoritative file is `pyproject.toml` at the repo root; this document
explains *what* must be in it and *why*, so a regenerated file stays
equivalent. Python **≥ 3.11** is required (uses `enum.StrEnum`, `X | Y`
unions, `datetime.UTC`).

## Runtime dependencies (`[project] dependencies`)

| Package | Floor | Why it is required |
|---|---|---|
| `pydantic` | ≥2.6 | All record models, LLM structured-output validation, schema artifacts |
| `pydantic-settings` | ≥2.2 | Typed config: YAML + `.env` + env-var layering (`YamlConfigSettingsSource`) |
| `PyYAML` | ≥6.0 | Config files, corpus-schema YAML artifacts, frontmatter |
| `SQLAlchemy` | ≥2.0 | ORM for the 31-table model; 2.x-style `Mapped`/`mapped_column` throughout |
| `alembic` | ≥1.13 | Database migrations (`render_as_batch` for SQLite/PG portability) |
| `typer` | ≥0.12 | The `kb` CLI |
| `rich` | ≥13.7 | CLI output (typer dependency; used for colored status) |
| `pymupdf` | ≥1.24 | Deterministic PDF parsing: text spans, TOC, `find_tables`. Import as `pymupdf` (the old `fitz` name is deprecated) |
| `httpx` | ≥0.27 | Sync client for the vLLM provider; `MockTransport` used in tests |
| `jsonschema` | ≥4.21 | Validating generated JSON Schema contracts (`validator_for().check_schema()`) |
| `structlog` | ≥24.1 | Structured logging (JSON in prod, console in dev) |

## Development dependencies (`[project.optional-dependencies] dev`)

| Package | Floor | Purpose |
|---|---|---|
| `pytest` | ≥8.0 | Test runner (`testpaths = ["tests"]`) |
| `pytest-cov` | ≥5.0 | Coverage reporting |
| `ruff` | ≥0.4 | Lint **and** format (line-length 100, rules `E,F,I,UP,B,SIM,RUF`) |
| `mypy` | ≥1.10 | Strict type checking (`strict = true`, pydantic plugin) |
| `types-PyYAML` | ≥6.0 | Stubs for mypy strict |
| `types-jsonschema` | (any) | Stubs for mypy strict |

## Environment-conditional packages (do NOT add to default deps)

| Package | When needed |
|---|---|
| `psycopg[binary]` | Only when `KB_DATABASE__URL` is a PostgreSQL DSN. Install alongside, e.g. `pip install "psycopg[binary]"`. Kept out of defaults so dev installs stay driver-free. |

## Non-negotiable `pyproject.toml` sections

1. **Build/layout**: setuptools backend, `packages.find` with `where = ["src"]`
   (src layout), `package-data` including `modelkb = ["llm/prompts/*.md"]` —
   prompt templates ship inside the wheel.
2. **Script**: `kb = "modelkb.cli:app"`.
3. **Ruff**: `line-length = 100`, `target-version = "py311"`, lint rules
   `["E","F","I","UP","B","SIM","RUF"]`.
4. **Mypy**: `strict = true`, `packages = ["modelkb"]`, pydantic plugin,
   `ignore_missing_imports` for `fitz.*`/`pymupdf.*`, and
   `disallow_untyped_calls = false` for `modelkb.pdf.*` (pymupdf's API is
   only partially typed).
5. **Pytest**: `testpaths = ["tests"]`, quiet output.

## Regeneration checklist

1. Create the venv and install: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
2. Verify: `.venv/bin/kb db-init` creates 32 tables (31 + `alembic_version`);
   `.venv/bin/python -m pytest tests/` passes; `ruff check` and `mypy` are clean.
3. Add a new runtime dependency only with a one-line justification in the
   table above — every dependency is audit surface in a governed system.

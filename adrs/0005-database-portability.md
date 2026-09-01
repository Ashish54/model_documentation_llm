# ADR 0005: PostgreSQL-targeted, SQLite-verified database strategy

## Status

Accepted (milestone 1)

## Context

The production target is PostgreSQL (JSONB, recursive traversal). The
development machine has neither a local PostgreSQL server nor Docker, and
tests must still run end-to-end today.

## Decision

* SQLAlchemy 2.x ORM + Alembic for all access; no raw SQL in application code.
* `JSONBCompat` TypeDecorator renders JSONB on PostgreSQL and JSON on SQLite.
* Enums are VARCHAR + app-level validation (`native_enum=False`) for
  dialect portability.
* `render_as_batch=True` in Alembic so the same migrations run on SQLite
  (table rebuilds) and PostgreSQL (native ALTER).
* The one FK cycle (`extraction_run` ↔ `schema_version`) is broken with
  `use_alter=True`, required for PostgreSQL creation order.
* Migration tests run on SQLite in CI today; when a PostgreSQL DSN becomes
  available, the same test module is re-run against it (documented in
  `tests/integration/test_migration.py`).

## Consequences

* Zero-install local development; production semantics preserved where they
  matter (JSONB ops, traversal indexes are PG-only by design).
* Risk accepted: SQLite does not enforce FK creation order or JSONB
  semantics, so a PG-backed CI job is required before production use.

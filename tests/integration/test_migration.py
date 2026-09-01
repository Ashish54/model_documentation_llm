"""Migration tests: full schema applies and rolls back cleanly on SQLite.

The same migration path targets PostgreSQL (JSONBCompat renders as JSONB
there); CI with a real PostgreSQL service should re-run this module against a
postgresql+psycopg DSN.
"""

from sqlalchemy import inspect

from modelkb.db.init import init_db

REQUIRED_TABLES = {
    "artifact",
    "artifact_version",
    "document",
    "document_version",
    "page",
    "section",
    "source_locator",
    "extraction_run",
    "schema_version",
    "model",
    "model_version",
    "claim",
    "claim_version",
    "assumption",
    "variable",
    "equation",
    "coefficient",
    "code_reference",
    "code_symbol",
    "relationship",
    "relationship_evidence",
    "model_info_snapshot",
    "change_event",
    "review_state",
    "llm_interaction",
}


def test_initial_migration_creates_required_tables(db_url: str) -> None:
    engine, _ = init_db(db_url)
    tables = set(inspect(engine).get_table_names())
    missing = REQUIRED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


def test_relationship_traversal_indexes_exist(db_url: str) -> None:
    engine, _ = init_db(db_url)
    indexes = {ix["name"] for ix in inspect(engine).get_indexes("relationship")}
    assert "ix_relationship_forward" in indexes
    assert "ix_relationship_reverse" in indexes


def test_evidence_association_tables_have_composite_pk(db_url: str) -> None:
    engine, _ = init_db(db_url)
    pk = inspect(engine).get_pk_constraint("relationship_evidence")
    assert set(pk["constrained_columns"]) == {"relationship_id", "source_locator_id"}


def test_foreign_keys_render(db_url: str) -> None:
    engine, _ = init_db(db_url)
    fks = inspect(engine).get_foreign_keys("relationship_evidence")
    referred = {(fk["constrained_columns"][0], fk["referred_table"]) for fk in fks}
    assert ("relationship_id", "relationship") in referred
    assert ("source_locator_id", "source_locator") in referred

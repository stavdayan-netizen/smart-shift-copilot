"""Alembic: the migrations build the schema, undo it, and never drift from the models."""
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db import Base, engine as app_engine
from app.migrations import alembic_config, schema_status, upgrade_to_head
from alembic import command

EXPECTED_TABLES = {"users", "conversations", "messages", "runs", "audit_log"}


@pytest.fixture
def fresh_url(tmp_path):
    """An empty database of the same kind as the one under test (SQLite file, or a new PostgreSQL database)."""
    if app_engine.dialect.name == "postgresql":
        name = f"mig_{uuid.uuid4().hex[:10]}"
        with app_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
        url = app_engine.url.set(database=name).render_as_string(hide_password=False)
        yield url
        with app_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    else:
        yield f"sqlite:///{tmp_path / 'fresh.db'}"


def test_there_is_exactly_one_head():
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_upgrade_creates_the_schema_and_downgrade_removes_it(fresh_url):
    upgrade_to_head(fresh_url)
    eng = create_engine(fresh_url)
    try:
        assert EXPECTED_TABLES <= set(inspect(eng).get_table_names())
        assert schema_status(eng)["state"] == "current"
        command.downgrade(alembic_config(fresh_url), "base")
        assert not (EXPECTED_TABLES & set(inspect(eng).get_table_names()))
        assert schema_status(eng)["state"] == "pending"
    finally:
        eng.dispose()


def test_models_and_migrations_agree(fresh_url):
    """If this fails, a model changed without a new Alembic revision (practice.md section 6)."""
    upgrade_to_head(fresh_url)
    eng = create_engine(fresh_url)
    try:
        with eng.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    finally:
        eng.dispose()
    assert diffs == [], f"models differ from migrations: {diffs}"


def test_database_under_test_is_at_head():
    assert schema_status(app_engine)["state"] == "current"


def test_audit_log_table_shape():
    cols = {c["name"] for c in inspect(app_engine).get_columns("audit_log")}
    assert {"id", "at", "actor_id", "action", "entity", "entity_id", "request_id", "before_json", "after_json"} <= cols

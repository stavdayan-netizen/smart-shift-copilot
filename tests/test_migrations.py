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

EXPECTED_TABLES = {"users", "conversations", "messages", "runs", "audit_log", "login_throttle"}


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


def test_user_access_columns_and_throttle_table_shape():
    insp = inspect(app_engine)
    users = {c["name"]: c for c in insp.get_columns("users")}
    assert {"access_role", "code_hash", "token_version"} <= set(users)
    assert users["code_hash"]["nullable"] is True and users["access_role"]["nullable"] is False
    throttle_cols = {c["name"] for c in insp.get_columns("login_throttle")}
    assert {"key", "failures", "locked_until", "updated_at"} <= throttle_cols
    assert "key" in insp.get_pk_constraint("login_throttle")["constrained_columns"]


def test_access_role_check_constraint_rejects_unknown_roles():
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal, User

    with SessionLocal() as s:
        s.add(User(name="Bad Role Person", access_role="superuser"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_0002_is_additive_existing_users_become_employees_without_a_code(tmp_path):
    """Upgrade a database that already has users (as 0001 left it) and check what the migration does to them."""
    from sqlalchemy import text

    if app_engine.dialect.name == "postgresql":
        return  # the same statements run in test_upgrade_creates_the_schema...; row-level check is SQLite-only here
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    command.upgrade(alembic_config(url), "0001")
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO users (name, created_at) VALUES ('Old User', '2026-01-01')"))
    command.upgrade(alembic_config(url), "head")
    with eng.connect() as conn:
        row = conn.execute(text("SELECT access_role, code_hash, token_version FROM users WHERE name='Old User'")).one()
    eng.dispose()
    assert tuple(row) == ("employee", None, 0)

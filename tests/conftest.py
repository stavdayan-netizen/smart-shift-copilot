"""Test setup: fake model, a throwaway database, a logged-in client.

The database is SQLite by default. Set TEST_DATABASE_URL to run the whole suite on
PostgreSQL (CI does): its `public` schema is dropped and rebuilt with Alembic.

Environment must be set before `app` is imported, because settings load once.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="smart-shift-tests-"))
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
os.environ.update({
    "MODEL_PROVIDER": "fake",
    "DATABASE_URL": TEST_DATABASE_URL or f"sqlite:///{_TMP / 'test.db'}",
    "APP_PASSWORD": "test-pass",
    "APP_SECRET": "test-secret-0123456789abcdef",
    "APP_ENV": "local",
    "DAILY_CAP_USD": "1.00",
    "RATE_LIMIT_PER_HOUR": "30",
    "CRON_SECRET": "cron-test",
    "ANTHROPIC_API_KEY": "",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import agent as agent_module  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrations import upgrade_to_head  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Build the schema with Alembic, exactly as a deploy does (never create_all)."""
    if TEST_DATABASE_URL and engine.dialect.name == "postgresql":
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            conn.exec_driver_sql("CREATE SCHEMA public")
    upgrade_to_head()
    yield


@pytest.fixture(scope="session")
def client(migrated_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def logged_in(client):
    r = client.post("/api/login", json={"name": "Tester", "password": "test-pass"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def fake(client):
    """The fake model behind the app; tests push scripted turns onto it."""
    fake_client = agent_module.FakeModelClient()
    app.state.model_client = fake_client
    yield fake_client
    fake_client.turns.clear()


@pytest.fixture
def log_lines():
    """Capture the app's JSON log lines. Call it for parsed dicts; .events(name) filters; .raw() is the text."""
    import io
    import json
    import logging

    from app.logging_setup import JsonFormatter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)

    class Lines:
        def raw(self) -> str:
            return buf.getvalue()

        def __call__(self) -> list[dict]:
            return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]

        def events(self, name: str) -> list[dict]:
            return [e for e in self() if e.get("event") == name]

    try:
        yield Lines()
    finally:
        root.removeHandler(handler)


def read_sse(response) -> list[dict]:
    import json

    events = []
    for chunk in response.text.split("\n\n"):
        for line in chunk.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events

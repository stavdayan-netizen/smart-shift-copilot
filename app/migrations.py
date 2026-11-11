"""Run and inspect Alembic migrations from Python (tests, evals, /health)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine

from .config import ROOT, settings


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(Path(ROOT) / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(ROOT) / "alembic"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade_to_head(url: str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")


def schema_status(engine: Engine) -> dict:
    """Compare the database's revision with the code's head: {"state": "current"|"pending", ...}."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return {"state": "current" if current == head else "pending", "current": current, "head": head}


def make_url_engine(url: str | None = None) -> Engine:
    return create_engine(url or settings.database_url)

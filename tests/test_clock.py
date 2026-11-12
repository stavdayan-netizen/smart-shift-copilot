"""The scheduling clock and its non-production override (app/clock.py, app/config.py)."""
import dataclasses
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import clock, config


def _env(monkeypatch, **values):
    for name in ("CLOCK_OVERRIDE", "APP_ENV", "MODEL_PROVIDER", "MANAGER_PASSWORD", "APP_SECRET"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    for k, v in values.items():
        if v is not None:
            monkeypatch.setenv(k, v)


def test_real_clock_is_aware_utc_and_not_overridden():
    assert not clock.is_overridden()
    now = clock.now()
    assert now.tzinfo is not None and now.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - now).total_seconds()) < 5


def test_override_freezes_the_clock(monkeypatch):
    frozen = datetime(2026, 11, 17, 19, 59, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "_override", frozen)
    assert clock.is_overridden() and clock.now() == frozen and clock.now() == frozen


@pytest.mark.parametrize("value", ["2026-11-17T21:59:30+02:00", "2026-11-17T19:59:30Z", "2026-11-17T19:59:30+00:00"])
def test_override_accepts_iso_instants_with_an_offset(monkeypatch, value):
    _env(monkeypatch, CLOCK_OVERRIDE=value)
    assert config.load_settings().clock_override == value
    assert clock._parse(value) == datetime(2026, 11, 17, 19, 59, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["2026-11-17T21:59:30", "not a date", "17/11/2026"])
def test_override_without_an_offset_or_unparseable_is_refused(monkeypatch, value):
    _env(monkeypatch, CLOCK_OVERRIDE=value)
    with pytest.raises(RuntimeError, match="CLOCK_OVERRIDE"):
        config.load_settings()


def test_override_is_refused_in_production(monkeypatch):
    _env(monkeypatch, APP_ENV="production", MODEL_PROVIDER="fake", MANAGER_PASSWORD="a-long-manager-password",
         APP_SECRET="s" * 40, CLOCK_OVERRIDE="2026-11-17T19:59:30Z")
    with pytest.raises(RuntimeError, match="not allowed in production"):
        config.load_settings()
    _env(monkeypatch, APP_ENV="production", MODEL_PROVIDER="fake", MANAGER_PASSWORD="a-long-manager-password", APP_SECRET="s" * 40)
    assert config.load_settings().clock_override is None   # production without it starts normally


def test_override_is_visible_in_health_and_in_logs(client, monkeypatch, log_lines):
    assert client.get("/health").json()["clock"] == "real"
    monkeypatch.setattr(clock, "_override", datetime(2026, 11, 17, 19, 59, 30, tzinfo=timezone.utc))
    assert client.get("/health").json()["clock"] == "override"
    from app.main import app

    with TestClient(app):
        pass
    start = log_lines.events("app_start")[-1]
    assert start["clock"] == "override"
    assert log_lines.events("clock_override_active")


def test_only_the_scheduling_cycle_uses_the_overridable_clock():
    """Logs, rate limits and sessions keep the real time (see app/clock.py)."""
    import pathlib
    import re

    used_by = {p.name for p in pathlib.Path(config.ROOT, "app").glob("*.py") if re.search(r"\bclock\.now\(\)", p.read_text(encoding="utf-8"))}
    assert used_by <= {"cycle_service.py", "clock.py", "main.py", "availability.py"}, used_by   # the cycle and what shows or gates it

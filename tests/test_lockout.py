"""Login lockout and rate limiting: kept in the database, identical for real and unknown names."""
import dataclasses
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import throttle
from app.config import settings
from app.db import LoginThrottle, SessionLocal, utcnow
from app.users import create_employee

H = {"X-Requested-With": "shift-copilot"}
BAD = "ZZZZZ-ZZZZZ"


@pytest.fixture
def clock(monkeypatch):
    """A controllable clock for the throttle."""
    state = {"t": utcnow()}
    monkeypatch.setattr(throttle, "now", lambda: state["t"])

    def advance(seconds):
        state["t"] = state["t"] + timedelta(seconds=seconds)

    return advance


def _attempt(client, name, code):
    return client.post("/api/login", json={"name": name, "code": code}, headers=H)


def test_five_failures_lock_the_account_even_for_the_right_code(client, db, clock):
    user, code = create_employee(db, "Lock Me")
    assert [_attempt(client, user.name, BAD).status_code for _ in range(5)] == [401] * 5
    blocked = _attempt(client, user.name, code)  # the correct code is refused while locked
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    assert "Too many attempts" in blocked.json()["detail"]
    clock(61)
    assert _attempt(client, user.name, code).status_code == 200


def test_unknown_names_are_locked_exactly_like_real_ones(client, db, clock):
    user, _ = create_employee(db, "Real Name")

    def sequence(name):
        out = [_attempt(client, name, BAD) for _ in range(6)]
        return [(r.status_code, r.headers.get("retry-after"), r.json()["detail"]) for r in out]

    real, unknown = sequence(user.name), sequence("Name That Does Not Exist")
    assert [s for s, _, _ in real] == [401] * 5 + [429]
    assert real[:5] == unknown[:5]
    assert real[5][:2] == unknown[5][:2] == (429, "60") and real[5][2] == unknown[5][2]


def test_backoff_grows_and_is_capped(client, db, clock):
    user, _ = create_employee(db, "Backoff")
    for _ in range(5):
        _attempt(client, user.name, BAD)
    waits = []
    for _ in range(7):
        clock(901)  # the lock has expired, and the counters are still younger than the 1 hour decay
        r = _attempt(client, user.name, BAD)
        assert r.status_code == 401
        blocked = _attempt(client, user.name, BAD)
        assert blocked.status_code == 429
        waits.append(int(blocked.headers["retry-after"]))
    assert waits[:4] == [120, 240, 480, 900] and max(waits) == 900


def test_success_clears_the_counter(client, db, clock):
    user, code = create_employee(db, "Clears")
    for _ in range(4):
        _attempt(client, user.name, BAD)
    assert _attempt(client, user.name, code).status_code == 200
    assert [_attempt(client, user.name, BAD).status_code for _ in range(4)] == [401] * 4  # a fresh count, no lock yet


def test_old_failures_are_forgotten(client, db, clock):
    user, code = create_employee(db, "Decays")
    for _ in range(4):
        _attempt(client, user.name, BAD)
    clock(3601 + 1)
    assert _attempt(client, user.name, BAD).status_code == 401  # counts as the first failure, not the fifth
    assert _attempt(client, user.name, code).status_code == 200


def test_lock_state_is_in_the_database_and_holds_no_names_or_addresses(client, db, clock):
    user, _ = create_employee(db, "Persisted Lock")
    for _ in range(5):
        _attempt(client, user.name, BAD)
    with SessionLocal() as other:  # a different session stands in for a different process or a restart
        rows = other.scalars(select(LoginThrottle)).all()
        assert rows and any(r.locked_until is not None for r in rows)
        assert all("persisted" not in r.key.lower() and "testclient" not in r.key for r in rows)
        assert throttle.blocked_for(other, [throttle.name_key(user.name)]) > 0
    assert throttle.name_key("persisted   LOCK") == throttle.name_key(user.name)  # spacing and case do not evade it


def test_per_ip_limit_applies_across_names(client, db, clock):
    user, code = create_employee(db, "Innocent Bystander")
    statuses = [_attempt(client, f"Spray Name {i}", BAD).status_code for i in range(20)]
    assert statuses == [401] * 20  # each name is far below its own limit
    r = _attempt(client, user.name, code)  # same address: blocked even with a valid code
    assert r.status_code == 429 and int(r.headers["retry-after"]) == 300


def test_two_sessions_never_lose_each_others_counts(db):
    key = throttle.name_key("atomic")
    policy = {"threshold": 100, "base": 1, "cap": 1}
    with SessionLocal() as a, SessionLocal() as b:
        for i in range(10):
            throttle.record_failure(a if i % 2 else b, key, **policy)
    with SessionLocal() as s:
        assert s.get(LoginThrottle, key).failures == 10


def test_concurrent_failures_are_all_counted(db):
    key = throttle.name_key("concurrent")
    policy = {"threshold": 1000, "base": 1, "cap": 1}
    errors = []

    def work():
        try:
            with SessionLocal() as s:
                for _ in range(5):
                    throttle.record_failure(s, key, **policy)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    with SessionLocal() as s:
        throttle.record_failure(s, key, **policy)  # create the row first so threads only increment
    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    with SessionLocal() as s:
        assert s.get(LoginThrottle, key).failures == 1 + 4 * 5


def test_idle_rows_are_purged(db, clock):
    with SessionLocal() as s:
        s.add(LoginThrottle(key="old" * 8, failures=2, updated_at=utcnow() - timedelta(days=3)))
        s.commit()
        throttle.record_failure(s, throttle.name_key("trigger purge"), **throttle.NAME_POLICY)
        assert s.get(LoginThrottle, "old" * 8) is None


def _request(headers=None, host="10.0.0.9"):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def test_forwarding_headers_are_ignored_unless_a_trusted_header_is_configured(monkeypatch):
    spoofed = {"x-forwarded-for": "1.2.3.4", "x-real-ip": "5.6.7.8"}
    assert throttle.client_ip(_request(spoofed)) == "10.0.0.9"  # default: the socket peer, never a client-supplied header
    monkeypatch.setattr(throttle, "settings", dataclasses.replace(settings, client_ip_header="x-real-ip"))
    assert throttle.client_ip(_request(spoofed)) == "5.6.7.8"
    assert throttle.client_ip(_request({"x-real-ip": "9.9.9.9, 5.6.7.8"})) == "5.6.7.8"  # the entry our proxy appended
    assert throttle.client_ip(_request({"x-real-ip": "not-an-ip"})) == "10.0.0.9"
    assert throttle.client_ip(_request({})) == "10.0.0.9"


def test_ip_limit_is_off_in_production_until_a_client_ip_source_is_configured(monkeypatch):
    prod = dataclasses.replace(settings, environment="production")
    monkeypatch.setattr(throttle, "settings", prod)
    assert throttle.ip_throttle_enabled() is False  # behind a proxy every user would share one address
    monkeypatch.setattr(throttle, "settings", dataclasses.replace(prod, client_ip_header="x-real-ip"))
    assert throttle.ip_throttle_enabled() is True
    monkeypatch.setattr(throttle, "settings", dataclasses.replace(settings, environment="local"))
    assert throttle.ip_throttle_enabled() is True


def test_lockout_is_logged_without_names_or_codes(client, db, clock, log_lines):
    user, _ = create_employee(db, "Quiet Logs")
    for _ in range(6):
        _attempt(client, user.name, BAD)
    raw = log_lines.raw()
    assert "Quiet Logs" not in raw and BAD not in raw
    blocked = log_lines.events("login_blocked")
    assert blocked and blocked[0]["scope"] == ["name"] and blocked[0]["retry_after"] == 60
    failed = log_lines.events("auth_failed")
    assert len(failed) == 5 and all(f["reason"] == "bad_credentials" for f in failed)

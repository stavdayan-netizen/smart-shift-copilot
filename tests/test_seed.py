"""`python -m app.seed`: fictional demo data, idempotent, never overwrites existing shift settings."""
import dataclasses
import re
from datetime import time

import pytest
from sqlalchemy import delete, select

from app import seed
from app.audit import AuditError
from app.config import settings
from app.db import AuditLog, Shift, User
from app.db import SessionLocal

CODE_RE = re.compile(r"\b[A-HJ-NP-Z2-9]{5}-[A-HJ-NP-Z2-9]{5}\b")
H = {"X-Requested-With": "shift-copilot"}


def _wipe_seeded():
    with SessionLocal() as s:
        s.execute(delete(User).where(User.name.in_(seed.DEMO_EMPLOYEES)))
        s.execute(delete(Shift).where(Shift.name.in_([n for n, *_ in seed.DEMO_SHIFTS])))
        s.commit()


@pytest.fixture
def clean_seed(client):
    """Start with none of the seeded rows and leave none behind (audit rows are append-only and stay)."""
    _wipe_seeded()
    yield
    _wipe_seeded()


def _audit_count(action):
    with SessionLocal() as s:
        return len(s.scalars(select(AuditLog.id).where(AuditLog.action == action)).all())


def test_seed_creates_two_shifts_and_eight_fictional_employees(clean_seed, db):
    before_shift, before_user = _audit_count("shift.created"), _audit_count("user.created")
    result = seed.run_seed(db)
    assert result.shifts_created == ["בוקר", "ערב"] and len(result.employees_created) == 8
    shifts = {s.name: s for s in db.scalars(select(Shift)).all() if s.name in ("בוקר", "ערב")}
    assert (shifts["בוקר"].start_time, shifts["בוקר"].end_time, shifts["בוקר"].required_staff) == (time(8, 0), time(16, 0), 2)
    assert (shifts["ערב"].start_time, shifts["ערב"].end_time, shifts["ערב"].required_staff) == (time(16, 0), time(0, 0), 2)
    employees = db.scalars(select(User).where(User.name.in_(seed.DEMO_EMPLOYEES))).all()
    assert {u.name for u in employees} == set(seed.DEMO_EMPLOYEES) and all(u.access_role == "employee" for u in employees)
    assert _audit_count("shift.created") == before_shift + 2 and _audit_count("user.created") == before_user + 8


def test_seeded_codes_are_one_time_hashed_and_work(clean_seed, db, client):
    result = seed.run_seed(db)
    codes = dict(result.employees_created)
    assert len(set(codes.values())) == 8 and all(CODE_RE.fullmatch(c) for c in codes.values())
    for user in db.scalars(select(User).where(User.name.in_(seed.DEMO_EMPLOYEES))).all():
        assert user.code_hash.startswith("scrypt$") and codes[user.name] not in user.code_hash
    name, code = next(iter(codes.items()))
    client.cookies.clear()
    r = client.post("/api/login", json={"name": name, "code": code})
    assert r.status_code == 200 and r.json()["role"] == "employee"


def test_a_second_run_creates_nothing_and_shows_no_codes(clean_seed, db):
    seed.run_seed(db)
    before_users, before_audit = db.query(User).count(), db.query(AuditLog).count()
    again = seed.run_seed(db)
    assert not again.shifts_created and not again.employees_created
    assert sorted(again.shifts_existing) == ["בוקר", "ערב"] and len(again.employees_existing) == 8
    assert db.query(User).count() == before_users and db.query(AuditLog).count() == before_audit


def test_existing_shift_settings_are_never_overwritten(clean_seed, db):
    seed.run_seed(db)
    morning = db.scalar(select(Shift).where(Shift.name == "בוקר"))
    morning.start_time, morning.end_time, morning.required_staff = time(9, 0), time(17, 0), 3
    db.commit()
    audit_before = db.query(AuditLog).count()
    seed.run_seed(db)
    db.expire_all()
    morning = db.scalar(select(Shift).where(Shift.name == "בוקר"))
    assert (morning.start_time, morning.end_time, morning.required_staff) == (time(9, 0), time(17, 0), 3)
    assert db.query(AuditLog).count() == audit_before                      # no change, so nothing audited


def test_a_missing_shift_is_added_and_the_others_are_left_alone(clean_seed, db):
    seed.run_seed(db)
    evening = db.scalar(select(Shift).where(Shift.name == "ערב"))
    evening.required_staff = 4
    db.delete(db.scalar(select(Shift).where(Shift.name == "בוקר")))
    db.commit()
    result = seed.run_seed(db)
    assert result.shifts_created == ["בוקר"] and result.shifts_existing == ["ערב"]
    db.expire_all()
    assert db.scalar(select(Shift.required_staff).where(Shift.name == "ערב")) == 4


def test_a_failing_audit_write_creates_no_shift(clean_seed, db, monkeypatch):
    def broken(*args, **kwargs):
        raise AuditError("audit down")

    monkeypatch.setattr(seed, "record", broken)
    with pytest.raises(AuditError):
        seed.seed_shifts(db, seed.SeedResult())
    assert db.query(Shift).filter(Shift.name.in_(["בוקר", "ערב"])).count() == 0


def test_the_command_prints_codes_once_and_never_logs_them(clean_seed, capsys, log_lines):
    assert seed.main([]) == 0
    out = capsys.readouterr().out
    codes = CODE_RE.findall(out)
    assert len(codes) == 8 and "8 created" in out
    assert not any(c in log_lines.raw() or c.replace("-", "") in log_lines.raw() for c in codes)
    run = log_lines.events("seed_run")[0]
    assert (run["shifts_created"], run["employees_created"]) == (2, 8)
    assert seed.main([]) == 0
    second = capsys.readouterr().out
    assert not CODE_RE.search(second) and "0 created" in second


def test_production_needs_an_explicit_confirmation(clean_seed, monkeypatch, capsys):
    monkeypatch.setattr(seed, "settings", dataclasses.replace(settings, environment="production"))
    assert seed.main([]) == 2
    assert "--confirm-fictional" in capsys.readouterr().err
    with SessionLocal() as s:
        assert s.query(Shift).filter(Shift.name.in_(["בוקר", "ערב"])).count() == 0
    assert seed.main(["--confirm-fictional"]) == 0
    with SessionLocal() as s:
        assert s.query(Shift).filter(Shift.name.in_(["בוקר", "ערב"])).count() == 2

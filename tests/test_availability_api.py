"""The availability form's API (app/availability.py): window gate, validation, isolation, audit, limits, logs."""
import dataclasses
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import availability, clock, cycle_service, limits, seed
from app.audit import AuditError
from app.config import settings
from app.db import AuditLog, AvailabilitySlot, AvailabilitySubmission, SessionLocal, Shift, User
from app.main import app
from app.users import create_employee

UTC = timezone.utc
H = {"X-Requested-With": "shift-copilot"}
HEBREW = re.compile(r"[֐-׿]")
OPEN_WEEK = date(2026, 11, 29)          # window: Thu 19 Nov 22:00 -> Tue 24 Nov 22:00 (Asia/Jerusalem)
SECRET_TEXT = "סודי-" + uuid.uuid4().hex[:8]


def freeze(monkeypatch, y, m, d, h=0, mi=0, s=0):
    monkeypatch.setattr(clock, "_override", datetime(y, m, d, h, mi, s, tzinfo=UTC))


def freeze_open(monkeypatch):
    freeze(monkeypatch, 2026, 11, 22, 10)       # Sunday 12:00 local: the 29 Nov window is open


@pytest.fixture
def shifts(db):
    """The two demo shifts, present for the test and removed (with anything pointing at them) afterwards."""
    def wipe():
        with SessionLocal() as s:
            for sub in s.scalars(select(AvailabilitySubmission)).all():
                s.delete(sub)
            s.commit()
            s.execute(delete(Shift).where(Shift.name.in_(["בוקר", "ערב"])))
            s.commit()

    wipe()
    seed.seed_shifts(db, seed.SeedResult())
    ids = {s.name: s.id for s in db.scalars(select(Shift)).all()}
    yield ids
    wipe()


def new_employee(db, name=None):
    name = name or f"Form {uuid.uuid4().hex[:8]}"
    user, code = create_employee(db, name)
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": name, "code": code}).status_code == 200
    return c, user


def body(shifts, *pairs, text=None, week=OPEN_WEEK):
    """pairs: (days after the week's Sunday, 'בוקר'|'ערב')."""
    return {"week_start": week.isoformat(),
            "slots": [{"day": (week + timedelta(days=d)).isoformat(), "shift_id": shifts[name]} for d, name in pairs],
            "free_text": text}


def saved_rows(user_id):
    with SessionLocal() as s:
        subs = s.scalars(select(AvailabilitySubmission).where(AvailabilitySubmission.user_id == user_id)).all()
        return [(sub.week_start, sorted((sl.day, sl.shift_id) for sl in sub.slots), sub.free_text) for sub in subs]


# ------------------------------------------------------------------ reading
def test_get_returns_the_week_the_days_the_shifts_and_the_window(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    data = emp.get("/api/availability").json()
    assert data["cycle"]["state"] == "open" and data["cycle"]["week_start"] == "2026-11-29"
    assert data["week"]["days"] == [(OPEN_WEEK + timedelta(days=i)).isoformat() for i in range(7)]
    assert [(s["name"], s["start_time"], s["end_time"], s["ends_next_day"]) for s in data["shifts"]] == [
        ("בוקר", "08:00", "16:00", False), ("ערב", "16:00", "00:00", True)]
    assert data["editable"] is True and data["submission"] is None and data["locked_week"] is None
    assert data["limits"] == {"free_text_max": 1000, "saves_per_hour": 20, "saves_left": 20}


def test_before_the_window_opens_the_form_is_not_editable(db, shifts, monkeypatch):
    freeze(monkeypatch, 2026, 11, 18, 7)                   # Wednesday, nothing published
    emp, _ = new_employee(db)
    data = emp.get("/api/availability").json()
    assert data["editable"] is False and data["cycle"]["state"] == "not_open"
    assert data["cycle"]["opens_at"] == "2026-11-19T22:00:00+02:00"


# ------------------------------------------------------------------ saving
def test_save_then_read_back_and_resubmit_replaces_everything(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    first = emp.put("/api/availability", json=body(shifts, (0, "בוקר"), (1, "ערב"), (6, "בוקר"), text="  מעדיפה בקרים\r\nתודה  "))
    assert first.status_code == 200 and first.json()["saved"] is True
    sub = first.json()["submission"]
    assert len(sub["slots"]) == 3 and sub["free_text"] == "מעדיפה בקרים\nתודה"
    assert sub["submitted_at"].endswith("Z") and sub["updated_at"].endswith("Z")
    second = emp.put("/api/availability", json=body(shifts, (2, "ערב"), text=None))
    got = second.json()["submission"]
    assert [(s["day"], s["shift_id"]) for s in got["slots"]] == [("2026-12-01", shifts["ערב"])] and got["free_text"] is None
    assert got["submitted_at"] == sub["submitted_at"]                            # the first submission time is kept
    assert len(saved_rows(user.id)) == 1                                           # latest values only, no history
    assert emp.get("/api/availability").json()["submission"]["slots"] == got["slots"]


def test_zero_available_shifts_is_refused_even_when_editing(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    r = emp.put("/api/availability", json=body(shifts))
    assert r.status_code == 422 and r.json()["detail"] == availability.MESSAGES["no_slots"]
    assert r.json()["errors"] == [{"field": "slots", "message": availability.MESSAGES["no_slots"]}]
    assert saved_rows(user.id) == []
    assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"))).status_code == 200
    assert emp.put("/api/availability", json=body(shifts)).status_code == 422
    assert len(saved_rows(user.id)[0][1]) == 1                                    # the earlier submission is untouched


def test_slot_validation(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    good = body(shifts, (0, "בוקר"))
    outside = {**good, "slots": [{"day": "2026-12-06", "shift_id": shifts["בוקר"]}]}
    assert emp.put("/api/availability", json=outside).json()["detail"] == availability.MESSAGES["bad_day"]
    unknown = {**good, "slots": [{"day": "2026-11-29", "shift_id": 987654}]}
    assert emp.put("/api/availability", json=unknown).json()["detail"] == availability.MESSAGES["bad_shift"]
    dup = {**good, "slots": good["slots"] * 2}
    assert emp.put("/api/availability", json=dup).json()["detail"] == availability.MESSAGES["duplicate"]
    assert saved_rows(user.id) == []


def test_free_text_limit_cleaning_and_extra_fields(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="א" * 1000)).status_code == 200
    r = emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="א" * 1001))
    assert r.status_code == 422 and r.json()["errors"] == [{"field": "free_text", "message": availability.MESSAGES["text_too_long"]}]
    assert len(saved_rows(user.id)[0][2]) == 1000
    cleaned = emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="שלום\x00\x07 עולם‏"))
    assert cleaned.json()["submission"]["free_text"] == "שלום עולם‏"           # control characters dropped, marks kept
    blank = emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="  \n \t "))
    assert blank.json()["submission"]["free_text"] is None
    # the trimmed length is what counts: a long padded text that cleans to 1000 is fine
    assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="  " + "ב" * 1000 + "  ")).status_code == 200


def test_unknown_or_forged_fields_and_malformed_requests_are_hebrew_422(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    other, other_user = new_employee(db)
    forged = {**body(shifts, (0, "בוקר")), "user_id": other_user.id}
    r = emp.put("/api/availability", json=forged)
    assert r.status_code == 422 and HEBREW.search(r.json()["detail"])
    for bad in ({"week_start": "not a date", "slots": []}, {"slots": []}, {"week_start": "2026-11-29", "slots": "x"},
                {"week_start": "2026-11-29", "slots": [{"day": "2026-11-29"}]},
                {"week_start": "2026-11-29", "slots": [{"day": "2026-11-29", "shift_id": 1, "role": "x"}]}):
        r = emp.put("/api/availability", json=bad)
        assert r.status_code == 422 and HEBREW.search(r.json()["detail"]) and "input" not in str(r.json()["errors"])
    assert saved_rows(user.id) == [] and saved_rows(other_user.id) == []
    assert emp.put("/api/availability", content="{not json", headers={**H, "Content-Type": "application/json"}).status_code == 422


# ------------------------------------------------------------------ the window gate (server enforced)
def test_window_boundaries_to_the_second(db, shifts, monkeypatch):
    emp, _ = new_employee(db)
    payload = body(shifts, (0, "בוקר"))
    freeze(monkeypatch, 2026, 11, 19, 19, 59, 59)                       # one second before Thursday 22:00 local
    r = emp.put("/api/availability", json=payload)
    assert r.status_code == 409 and r.json()["detail"] == cycle_service.MESSAGES["not_open"]
    freeze(monkeypatch, 2026, 11, 19, 20, 0, 0)                         # Thursday 22:00 exactly
    assert emp.put("/api/availability", json=payload).status_code == 200
    freeze(monkeypatch, 2026, 11, 24, 19, 59, 59)                       # the last second before Tuesday 22:00
    assert emp.put("/api/availability", json=payload).status_code == 200
    freeze(monkeypatch, 2026, 11, 24, 20, 0, 0)                         # Tuesday 22:00 exactly
    r = emp.put("/api/availability", json=payload)
    assert r.status_code == 409 and r.json()["detail"] == cycle_service.MESSAGES["closed"]


@pytest.mark.parametrize("week,close_utc", [(date(2026, 11, 1), (2026, 10, 27, 20)),    # spans the autumn change (+03:00 -> +02:00)
                                           (date(2026, 4, 5), (2026, 3, 31, 19))])      # spans the spring change (+02:00 -> +03:00)
def test_the_deadline_is_tuesday_22_00_local_in_dst_weeks(db, shifts, monkeypatch, week, close_utc):
    emp, _ = new_employee(db)
    payload = body(shifts, (0, "בוקר"), week=week)
    y, m, d, h = close_utc
    freeze(monkeypatch, y, m, d, h - 1, 59, 59)
    assert emp.put("/api/availability", json=payload).status_code == 200
    freeze(monkeypatch, y, m, d, h, 0, 0)
    assert emp.put("/api/availability", json=payload).status_code == 409


def test_only_the_open_week_can_be_written(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, _ = new_employee(db)
    for week in (date(2026, 11, 22), date(2026, 12, 6), date(2027, 3, 7)):
        assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"), week=week)).status_code == 409
    assert emp.put("/api/availability", json={**body(shifts, (0, "בוקר")), "week_start": "2026-11-30"}).status_code == 400


def test_a_first_publication_opens_the_window_early(db, shifts, monkeypatch):
    freeze(monkeypatch, 2026, 11, 18, 7)
    emp, _ = new_employee(db)
    payload = body(shifts, (0, "בוקר"))
    assert emp.put("/api/availability", json=payload).status_code == 409
    published = datetime(2026, 11, 18, 5, tzinfo=UTC)
    monkeypatch.setattr(cycle_service, "first_publication_of", lambda d, w: published if w == date(2026, 11, 22) else None)
    assert emp.put("/api/availability", json=payload).status_code == 200


def test_after_the_deadline_the_submission_is_visible_read_only_and_cannot_change(db, shifts, monkeypatch):
    freeze(monkeypatch, 2026, 11, 16, 12)                               # Monday: the 22 Nov window is open
    emp, _ = new_employee(db)
    saved = emp.put("/api/availability", json=body(shifts, (0, "בוקר"), (3, "ערב"), text="בבקשה", week=date(2026, 11, 22)))
    assert saved.status_code == 200
    freeze(monkeypatch, 2026, 11, 18, 7)                                # after Tuesday 22:00, 29 Nov not open yet
    data = emp.get("/api/availability").json()
    assert data["editable"] is False and data["submission"] is None
    locked = data["locked_week"]
    assert locked["week_start"] == "2026-11-22" and locked["week_end"] == "2026-11-28"
    assert len(locked["submission"]["slots"]) == 2 and locked["submission"]["free_text"] == "בבקשה"
    assert emp.put("/api/availability", json=body(shifts, (1, "ערב"), week=date(2026, 11, 22))).status_code == 409
    assert saved_rows(_.id)[0][1] and len(saved_rows(_.id)[0][1]) == 2


# ------------------------------------------------------------------ isolation and roles
def test_employees_cannot_see_or_change_each_others_submissions(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    a, user_a = new_employee(db)
    b, user_b = new_employee(db)
    a.put("/api/availability", json=body(shifts, (0, "בוקר"), text=SECRET_TEXT))
    assert b.get("/api/availability").json()["submission"] is None
    assert SECRET_TEXT not in b.get("/api/availability").text
    b.put("/api/availability", json=body(shifts, (4, "ערב")))
    assert saved_rows(user_a.id)[0][2] == SECRET_TEXT and len(saved_rows(user_a.id)) == 1
    assert [s["day"] for s in a.get("/api/availability").json()["submission"]["slots"]] == ["2026-11-29"]
    assert b.put("/api/availability", json={**body(shifts, (4, "ערב")), "user_id": user_a.id}).status_code == 422
    assert [s["day"] for s in a.get("/api/availability").json()["submission"]["slots"]] == ["2026-11-29"]


def test_manager_and_anonymous_cannot_use_the_employee_form(client, db, shifts, logged_in, monkeypatch):
    freeze_open(monkeypatch)
    assert client.get("/api/availability").status_code == 403
    assert client.put("/api/availability", json=body(shifts, (0, "בוקר"))).status_code == 403
    anon = TestClient(app, headers=H)
    assert anon.get("/api/availability").status_code == 401 and anon.put("/api/availability", json={}).status_code == 401


def test_a_save_without_the_csrf_header_is_blocked(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    r = emp.put("/api/availability", json=body(shifts, (0, "בוקר")), headers={"X-Requested-With": ""})
    assert r.status_code == 403 and saved_rows(user.id) == []


# ------------------------------------------------------------------ the 20 per hour limit
def test_default_limit_is_twenty_per_hour():
    assert settings.availability_saves_per_hour == 20 and limits.saves_per_hour() == 20


def test_saves_beyond_the_limit_get_429_and_failed_saves_do_not_count(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    monkeypatch.setattr(limits, "settings", dataclasses.replace(settings, availability_saves_per_hour=3))
    emp, user = new_employee(db)
    other, _ = new_employee(db)
    for _ in range(6):                                                    # invalid saves are free
        assert emp.put("/api/availability", json=body(shifts)).status_code == 422
    for i in range(3):
        assert emp.put("/api/availability", json=body(shifts, (i, "בוקר"))).status_code == 200
    r = emp.put("/api/availability", json=body(shifts, (5, "בוקר")))
    assert r.status_code == 429 and HEBREW.search(r.json()["detail"]) and "3" in r.json()["detail"]
    assert 3500 < int(r.headers["retry-after"]) <= 3600
    assert emp.get("/api/availability").json()["limits"]["saves_left"] == 0
    assert len(saved_rows(user.id)[0][1]) == 1                            # the refused save changed nothing (last good: day 2)
    assert other.put("/api/availability", json=body(shifts, (0, "בוקר"))).status_code == 200   # per employee


def test_the_limit_window_slides(db, shifts, monkeypatch):
    monkeypatch.setattr(limits, "settings", dataclasses.replace(settings, availability_saves_per_hour=2))
    user, _ = create_employee(db, f"Slide {uuid.uuid4().hex[:6]}")
    now = datetime(2026, 11, 22, 12, 0, 0)
    from app.audit import audited, record
    for minutes_ago in (50, 10):
        with audited(db):
            row = record(db, actor_id=user.id, action="availability.submitted", entity="availability_submission", entity_id=1, after={"slots": 1})
        db.execute(AuditLog.__table__.update().where(AuditLog.id == row.id).values(at=now - timedelta(minutes=minutes_ago)))
        db.commit()
    with pytest.raises(Exception) as info:
        limits.check_availability_save_limit(db, user.id, now)
    assert info.value.status_code == 429 and int(info.value.headers["Retry-After"]) == 10 * 60    # the oldest leaves in 10 minutes
    limits.check_availability_save_limit(db, user.id, now + timedelta(minutes=11))                  # one has aged out
    assert limits.availability_saves_left(db, user.id, now + timedelta(minutes=61)) == 2


# ------------------------------------------------------------------ audit and logs
def test_each_save_writes_one_audit_row_with_counts_only(db, shifts, monkeypatch, log_lines):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    emp.put("/api/availability", json=body(shifts, (0, "בוקר"), (1, "ערב"), text=SECRET_TEXT))
    emp.put("/api/availability", json=body(shifts, (2, "ערב"), text=None))
    with SessionLocal() as s:
        rows = s.scalars(select(AuditLog).where(AuditLog.actor_id == user.id, AuditLog.action == "availability.submitted").order_by(AuditLog.id)).all()
    assert [r.after_json for r in rows] == [
        {"week_start": "2026-11-29", "slots": 2, "has_free_text": True, "created": True},
        {"week_start": "2026-11-29", "slots": 1, "has_free_text": False, "created": False}]
    assert SECRET_TEXT not in str([r.after_json for r in rows]) and all(r.request_id for r in rows)
    events = log_lines.events("availability_submitted")
    assert [(e["slots"], e["has_free_text"], e["free_text_len"], e["created"]) for e in events] == [(2, True, len(SECRET_TEXT), True), (1, False, 0, False)]
    assert SECRET_TEXT not in log_lines.raw()


def test_a_failing_audit_write_means_nothing_is_saved(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    quiet = TestClient(app, headers=H, raise_server_exceptions=False)
    quiet.cookies.update(emp.cookies)
    assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"), text="לפני")).status_code == 200

    def broken(*args, **kwargs):
        raise AuditError("audit down")

    monkeypatch.setattr(availability, "record", broken)
    assert quiet.put("/api/availability", json=body(shifts, (3, "ערב"), text="אחרי")).status_code == 500
    assert saved_rows(user.id) == [(OPEN_WEEK, [(OPEN_WEEK, shifts["בוקר"])], "לפני")]    # still the first submission


def test_two_first_saves_at_once_become_a_save_and_an_update(db, shifts, monkeypatch):
    freeze_open(monkeypatch)
    emp, user = new_employee(db)
    with SessionLocal() as other:                                       # a competing request already inserted the row
        other.add(AvailabilitySubmission(user_id=user.id, week_start=OPEN_WEEK))
        other.commit()
    real = availability._submission
    calls = []

    def stale_then_real(db_, user_id, week):
        calls.append(1)
        return None if len(calls) == 1 else real(db_, user_id, week)

    monkeypatch.setattr(availability, "_submission", stale_then_real)
    assert emp.put("/api/availability", json=body(shifts, (0, "בוקר"))).status_code == 200
    assert len(saved_rows(user.id)) == 1 and len(saved_rows(user.id)[0][1]) == 1


def test_no_shifts_configured_is_a_clear_hebrew_error(db, monkeypatch):
    freeze_open(monkeypatch)
    with SessionLocal() as s:
        for sub in s.scalars(select(AvailabilitySubmission)).all():
            s.delete(sub)
        s.commit()
        s.execute(delete(Shift).where(Shift.name.in_(["בוקר", "ערב"])))
        s.commit()
    emp, _ = new_employee(db)
    assert emp.get("/api/availability").json()["shifts"] == [] or all(s["name"].startswith(("test", "avail", "dup")) for s in emp.get("/api/availability").json()["shifts"])
    r = emp.put("/api/availability", json={"week_start": OPEN_WEEK.isoformat(), "slots": [{"day": OPEN_WEEK.isoformat(), "shift_id": 1}]})
    assert r.status_code == 422


def test_all_form_messages_are_hebrew():
    assert all(HEBREW.search(m) for m in availability.MESSAGES.values())
    assert availability.FREE_TEXT_MAX == 1000

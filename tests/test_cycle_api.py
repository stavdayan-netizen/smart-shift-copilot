"""GET /api/cycle and the server-side window gate (app/cycle_service.py), driven by the non-production clock override."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import clock, cycle, cycle_service
from app.main import app
from app.users import create_employee

UTC = timezone.utc
H = {"X-Requested-With": "shift-copilot"}


def freeze(monkeypatch, y, m, d, h=0, mi=0, s=0):
    monkeypatch.setattr(clock, "_override", datetime(y, m, d, h, mi, s, tzinfo=UTC))


def test_wednesday_18_nov_with_nothing_published_the_next_window_opens_thursday_22_00(client, logged_in, monkeypatch):
    freeze(monkeypatch, 2026, 11, 18, 7)                        # Wednesday 09:00 local
    body = client.get("/api/cycle").json()
    assert body["week_start"] == "2026-11-29" and body["week_end"] == "2026-12-05" and body["state"] == "not_open"
    assert body["opens_at"] == "2026-11-19T22:00:00+02:00" and body["closes_at"] == "2026-11-24T22:00:00+02:00"
    assert body["opens_early_on_publication"] is True and body["opened_by_publication"] is False
    assert body["clock_overridden"] is True and body["timezone"] == "Asia/Jerusalem"
    assert body["seconds_until_opens"] == 37 * 3600                      # Wed 07:00Z to Thu 20:00Z
    assert body["seconds_until_closes"] == (6 * 24 + 13) * 3600          # to Tue 24 Nov 20:00Z


def test_after_a_first_publication_the_window_is_open_immediately(client, logged_in, monkeypatch):
    freeze(monkeypatch, 2026, 11, 18, 7)
    published = datetime(2026, 11, 18, 5, tzinfo=UTC)
    monkeypatch.setattr(cycle_service, "first_publication_of", lambda db, week: published if week == date(2026, 11, 22) else None)
    body = client.get("/api/cycle").json()
    assert body["state"] == "open" and body["opened_by_publication"] is True and body["opens_early_on_publication"] is False
    assert body["opens_at"] == "2026-11-18T07:00:00+02:00" and body["seconds_until_opens"] is None
    assert body["seconds_until_closes"] == int((datetime(2026, 11, 24, 20, tzinfo=UTC) - datetime(2026, 11, 18, 7, tzinfo=UTC)).total_seconds())


def test_the_target_week_moves_on_at_the_deadline_second(client, logged_in, monkeypatch):
    freeze(monkeypatch, 2026, 11, 17, 19, 59, 59)               # one second before Tuesday 22:00 local
    assert client.get("/api/cycle").json()["week_start"] == "2026-11-22"
    freeze(monkeypatch, 2026, 11, 17, 20, 0, 0)
    body = client.get("/api/cycle").json()
    assert body["week_start"] == "2026-11-29" and body["state"] == "not_open"


def test_open_and_closed_states_around_the_window(client, logged_in, monkeypatch):
    freeze(monkeypatch, 2026, 11, 22, 12)                        # Sunday 22 Nov: the 29 Nov window opened on Thursday 19th
    body = client.get("/api/cycle").json()
    assert body["state"] == "open" and body["week_start"] == "2026-11-29"
    assert body["seconds_until_opens"] is None and body["seconds_until_closes"] > 0


def test_employees_can_read_the_status_and_it_exposes_no_schedule_data(client, db, monkeypatch):
    freeze(monkeypatch, 2026, 11, 22, 12)
    user, code = create_employee(db, "Cycle Reader")
    emp = TestClient(app, headers=H)
    assert emp.post("/api/login", json={"name": user.name, "code": code}).status_code == 200
    body = emp.get("/api/cycle").json()
    assert set(body) == {"timezone", "now", "clock_overridden", "week_start", "week_end", "state", "opens_at", "closes_at",
                         "latest_opens_at", "opened_by_publication", "opens_early_on_publication", "seconds_until_opens",
                         "seconds_until_closes"}
    assert TestClient(app, headers=H).get("/api/cycle").status_code == 401


# ------------------------------------------------------------------ the server-side gate
def test_the_gate_rejects_before_the_window_opens_and_after_the_deadline(db, monkeypatch, log_lines):
    week = date(2026, 11, 29)
    freeze(monkeypatch, 2026, 11, 19, 19, 59, 59)               # one second before Thursday 22:00 local
    with pytest.raises(HTTPException) as info:
        cycle_service.enforce_window(db, week)
    assert info.value.status_code == 409 and info.value.detail == cycle_service.MESSAGES["not_open"]
    freeze(monkeypatch, 2026, 11, 19, 20, 0, 0)                 # Thursday 22:00 exactly: open
    assert cycle_service.enforce_window(db, week).week_start == week
    freeze(monkeypatch, 2026, 11, 24, 19, 59, 59)               # last second before Tuesday 22:00
    cycle_service.enforce_window(db, week)
    freeze(monkeypatch, 2026, 11, 24, 20, 0, 0)                 # Tuesday 22:00 exactly: closed
    with pytest.raises(HTTPException) as info:
        cycle_service.enforce_window(db, week)
    assert info.value.status_code == 409 and info.value.detail == cycle_service.MESSAGES["closed"]
    events = log_lines.events("window_rejected")
    assert [e["state"] for e in events] == ["not_open", "closed"] and all(e["level"] == "warning" for e in events)


def test_the_gate_honours_a_first_publication_and_ignores_far_weeks(db, monkeypatch):
    freeze(monkeypatch, 2026, 11, 18, 7)
    week = date(2026, 11, 29)
    with pytest.raises(HTTPException):
        cycle_service.enforce_window(db, week)
    monkeypatch.setattr(cycle_service, "first_publication_of", lambda d, w: datetime(2026, 11, 18, 5, tzinfo=UTC) if w == date(2026, 11, 22) else None)
    assert cycle_service.enforce_window(db, week).opened_by_publication
    for other in (date(2026, 12, 6), date(2027, 3, 7), date(2026, 11, 22), date(2026, 11, 15)):
        with pytest.raises(HTTPException) as info:
            cycle_service.enforce_window(db, other)
        assert info.value.status_code == 409


def test_the_gate_rejects_a_date_that_is_not_a_sunday(db, monkeypatch):
    freeze(monkeypatch, 2026, 11, 22, 12)
    with pytest.raises(HTTPException) as info:
        cycle_service.enforce_window(db, date(2026, 11, 30))
    assert info.value.status_code == 400


def test_a_late_publication_never_changes_an_open_window_and_the_deadline_is_fixed(db, monkeypatch):
    week = date(2026, 11, 29)
    freeze(monkeypatch, 2026, 11, 20, 12)                      # open since Thursday
    base = cycle_service.enforce_window(db, week)
    monkeypatch.setattr(cycle_service, "first_publication_of", lambda d, w: datetime(2026, 11, 21, 8, tzinfo=UTC))
    later = cycle_service.enforce_window(db, week)
    assert later.opens_at == base.opens_at and later.closes_at == base.closes_at


def test_until_schedules_exist_nothing_counts_as_published(db):
    assert cycle_service.first_publication_of(db, date(2026, 11, 22)) is None


def test_messages_are_hebrew():
    import re
    assert all(re.search(r"[֐-׿]", m) for m in cycle_service.MESSAGES.values())


def test_gate_works_with_the_real_clock_too(db):
    far_past = cycle.week_start_of(date(2020, 1, 1))
    with pytest.raises(HTTPException) as info:
        cycle_service.enforce_window(db, far_past)
    assert info.value.detail == cycle_service.MESSAGES["closed"]
    assert abs((clock.now() - datetime.now(UTC)) / timedelta(seconds=1)) < 5

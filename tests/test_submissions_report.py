"""The manager's read-only submissions report (app/submissions.py, GET /api/submissions)."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import clock, leave, seed
from app.db import AvailabilitySlot, AvailabilitySubmission, SessionLocal, Shift
from app.main import app
from app.users import create_employee

UTC = timezone.utc
H = {"X-Requested-With": "shift-copilot"}
WEEK = date(2026, 11, 29)                        # window open Thu 19 Nov 22:00 -> Tue 24 Nov 22:00


@pytest.fixture(autouse=True)
def frozen_open(monkeypatch):
    monkeypatch.setattr(clock, "_override", datetime(2026, 11, 22, 10, tzinfo=UTC))


@pytest.fixture
def world(db):
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
    tag = uuid.uuid4().hex[:6]
    users = {k: create_employee(db, f"{k}{tag}")[0] for k in ("Anna", "Boaz", "Chen", "Dror")}
    for k, free, slots in (("Anna", "רק בבקרים <b>תודה</b>", [(0, "בוקר"), (0, "ערב"), (2, "ערב")]), ("Boaz", None, [(1, "בוקר")])):
        sub = AvailabilitySubmission(user_id=users[k].id, week_start=WEEK, free_text=free)
        sub.slots = [AvailabilitySlot(day=WEEK + timedelta(days=d), shift_id=ids[n]) for d, n in slots]
        db.add(sub)
    db.commit()
    yield users
    wipe()


def manager():
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": "boss", "code": "test-manager-password"}).status_code == 200
    return c


def row(report, user):
    return next(r for r in report["employees"] if r["id"] == user.id)


def test_report_for_the_target_week_with_exact_shifts_and_free_text(world):
    r = manager().get("/api/submissions")
    assert r.status_code == 200
    rep = r.json()
    assert rep["week"]["start"] == "2026-11-29" and rep["cycle"]["state"] == "open"
    anna = row(rep, world["Anna"])
    assert anna["status"] == "submitted" and anna["free_text"] == "רק בבקרים <b>תודה</b>"   # returned as data; the UI shows text only
    assert [(d["date"], [(s["name"], s["start_time"], s["end_time"], s["ends_next_day"]) for s in d["shifts"]]) for d in anna["days"]] == [
        ("2026-11-29", [("בוקר", "08:00", "16:00", False), ("ערב", "16:00", "00:00", True)]),
        ("2026-12-01", [("ערב", "16:00", "00:00", True)])]
    boaz = row(rep, world["Boaz"])
    assert boaz["status"] == "submitted" and boaz["free_text"] is None and len(boaz["days"]) == 1
    for k in ("Chen", "Dror"):
        miss = row(rep, world[k])
        assert miss["status"] == "missing" and miss["days"] == [] and miss["free_text"] is None and miss["leave_dates"] == []


def test_counts_add_up_and_the_manager_is_not_an_employee(world):
    rep = manager().get("/api/submissions").json()
    c = rep["counts"]
    assert c["total"] == len(rep["employees"]) == c["submitted"] + c["missing"] + c["exempt"]
    assert c["submitted"] >= 2 and c["missing"] >= 2 and c["exempt"] == 0
    assert "boss" not in {r["name"] for r in rep["employees"]}


def test_there_is_no_leave_data_yet_so_nobody_has_leave_or_is_exempt(world):
    rep = manager().get("/api/submissions").json()
    assert all(r["leave_dates"] == [] and r["full_week_leave"] is False for r in rep["employees"])


def test_full_week_approved_leave_exempts_and_is_not_missing(world, monkeypatch):
    week = [WEEK + timedelta(days=i) for i in range(7)]
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Chen"].id: set(week)})
    rep = manager().get("/api/submissions").json()
    chen = row(rep, world["Chen"])
    assert chen["status"] == "exempt" and chen["full_week_leave"] is True and len(chen["leave_dates"]) == 7
    assert row(rep, world["Dror"])["status"] == "missing"
    assert rep["counts"]["exempt"] == 1 and rep["counts"]["missing"] == rep["counts"]["total"] - rep["counts"]["submitted"] - 1


def test_partial_leave_is_shown_next_to_the_submission_status_and_exempts_nobody(world, monkeypatch):
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Anna"].id: {WEEK + timedelta(days=3), WEEK + timedelta(days=4)},
                                                                world["Dror"].id: {WEEK + timedelta(days=1)},
                                                                world["Boaz"].id: {WEEK + timedelta(days=30)}})  # outside the week: ignored
    rep = manager().get("/api/submissions").json()
    anna = row(rep, world["Anna"])
    assert anna["status"] == "submitted" and anna["leave_dates"] == ["2026-12-02", "2026-12-03"] and anna["full_week_leave"] is False
    dror = row(rep, world["Dror"])
    assert dror["status"] == "missing" and dror["leave_dates"] == ["2026-11-30"]
    assert row(rep, world["Boaz"])["leave_dates"] == []


def test_leave_never_hides_an_existing_submission(world, monkeypatch):
    week = [WEEK + timedelta(days=i) for i in range(7)]
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Anna"].id: set(week)})
    anna = row(manager().get("/api/submissions").json(), world["Anna"])
    assert anna["status"] == "submitted" and len(anna["days"]) == 2 and anna["full_week_leave"] is True


def test_after_the_deadline_the_report_still_shows_the_target_week(world, monkeypatch):
    monkeypatch.setattr(clock, "_override", datetime(2026, 11, 25, 10, tzinfo=UTC))   # Wednesday after the Tuesday 22:00 deadline
    rep = manager().get("/api/submissions").json()
    assert rep["cycle"]["state"] == "closed" and rep["week"]["start"] == "2026-11-29"
    assert row(rep, world["Anna"])["status"] == "submitted"


def test_only_the_manager_may_read_it(world, db):
    assert TestClient(app, headers=H).get("/api/submissions").status_code == 401
    user, code = create_employee(db, f"Emp{uuid.uuid4().hex[:6]}")
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": user.name, "code": code}).status_code == 200
    assert c.get("/api/submissions").status_code == 403


def test_the_report_is_read_only(world):
    c = manager()
    assert c.get("/api/submissions").status_code == 200
    for method in ("post", "put", "delete", "patch"):
        assert getattr(c, method)("/api/submissions").status_code in (404, 405)


def test_employees_with_missing_submissions_are_listed_first(world, monkeypatch):
    week = [WEEK + timedelta(days=i) for i in range(7)]
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Chen"].id: set(week)})
    rep = manager().get("/api/submissions").json()
    rank = {"missing": 0, "exempt": 1, "submitted": 2}
    ranks = [rank[r["status"]] for r in rep["employees"]]
    assert ranks == sorted(ranks)                                         # missing, then exempt, then submitted
    for status in ("missing", "exempt", "submitted"):
        names = [r["name"] for r in rep["employees"] if r["status"] == status]
        assert names == sorted(names)                                     # by name inside each group
    assert rep["employees"][0]["status"] == "missing" and rep["employees"][-1]["status"] == "submitted"

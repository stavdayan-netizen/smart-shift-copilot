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


def test_default_order_is_submitted_newest_first_then_missing_by_name_then_exempt(world, monkeypatch):
    week = [WEEK + timedelta(days=i) for i in range(7)]
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Dror"].id: set(week)})      # Dror: full-week leave, no submission
    rep = manager().get("/api/submissions").json()
    rows = rep["employees"]
    rank = {"submitted": 0, "missing": 1, "exempt": 2}
    assert [rank[r["status"]] for r in rows] == sorted(rank[r["status"]] for r in rows)
    submitted = [r for r in rows if r["status"] == "submitted"]
    assert [r["updated_at"] for r in submitted] == sorted((r["updated_at"] for r in submitted), reverse=True)     # newest first
    for status in ("missing", "exempt"):
        names = [r["name"] for r in rows if r["status"] == status]
        assert names == sorted(names)                                                                              # by name
    assert rows[0]["status"] == "submitted" and rows[-1]["status"] == "exempt" and rows[-1]["id"] == world["Dror"].id


def test_every_submitted_employee_carries_a_timestamp_and_nobody_else_does(world):
    rows = manager().get("/api/submissions").json()["employees"]
    for r in rows:
        assert (r["updated_at"] is not None) == (r["status"] == "submitted")
        if r["updated_at"]:
            assert r["updated_at"].endswith("Z")                                                                    # UTC, shown in Israel time by the UI


def test_leave_filter_shows_only_full_week_exempt_employees_never_partial_leave(world, monkeypatch):
    week = [WEEK + timedelta(days=i) for i in range(7)]
    monkeypatch.setattr(leave, "approved_leave", lambda db, w: {world["Chen"].id: set(week), world["Anna"].id: {WEEK + timedelta(days=2)}})
    rep = manager().get("/api/submissions").json()
    on_leave = [r["name"] for r in rep["employees"] if r["status"] == "exempt"]
    assert on_leave == [world["Chen"].name] and rep["counts"]["exempt"] == 1                                       # the "בחופשה" card
    anna = row(rep, world["Anna"])
    assert anna["status"] == "submitted" and anna["leave_dates"] and not anna["full_week_leave"]                    # partial leave stays with her status


def test_without_leave_data_the_on_leave_count_is_zero_and_nobody_is_listed(world):
    rep = manager().get("/api/submissions").json()
    assert rep["counts"]["exempt"] == 0 and not [r for r in rep["employees"] if r["status"] == "exempt"]
    assert all(r["leave_dates"] == [] for r in rep["employees"])                                                     # nothing is invented


def test_counts_order_and_timestamps_follow_new_submissions_and_edits(world, db):
    import time

    from app import availability  # noqa: F401  (the real endpoints are used below)

    ids = {s.name: s.id for s in db.scalars(select(Shift)).all()}
    tag = uuid.uuid4().hex[:6]
    emps = {k: create_employee(db, f"Live{k}{tag}") for k in ("A", "B")}

    def login(user, code):
        c = TestClient(app, headers=H)
        assert c.post("/api/login", json={"name": user.name, "code": code}).status_code == 200
        return c

    def save(client, *pairs, text=None):
        body = {"week_start": WEEK.isoformat(), "slots": [{"day": (WEEK + timedelta(days=d)).isoformat(), "shift_id": ids[n]} for d, n in pairs], "free_text": text}
        assert client.put("/api/availability", json=body).status_code == 200

    m = manager()
    before = m.get("/api/submissions").json()
    ca, cb = login(*emps["A"]), login(*emps["B"])
    save(ca, (0, "בוקר"))
    time.sleep(0.05)
    save(cb, (1, "ערב"), text="שלום")
    rep = m.get("/api/submissions").json()
    order = [r["name"] for r in rep["employees"] if r["name"].startswith("Live")]
    assert order == [emps["B"][0].name, emps["A"][0].name]                                                           # B submitted last: newest first
    assert rep["counts"]["submitted"] == before["counts"]["submitted"] + 2 and rep["counts"]["missing"] == before["counts"]["missing"] - 2
    t_a = row(rep, emps["A"][0])["updated_at"]
    time.sleep(0.05)
    save(ca, (0, "בוקר"), (3, "ערב"))                                                                                # A edits: moves to the top, timestamp moves
    rep2 = m.get("/api/submissions").json()
    assert [r["name"] for r in rep2["employees"] if r["name"].startswith("Live")] == [emps["A"][0].name, emps["B"][0].name]
    a2 = row(rep2, emps["A"][0])
    assert a2["updated_at"] > t_a and len(a2["days"]) == 2
    assert rep2["counts"] == rep["counts"]                                                                           # an edit does not change the counts

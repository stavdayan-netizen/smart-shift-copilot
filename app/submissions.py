"""The manager's read-only view of the target week's availability submissions ("הגשות עובדים").

GET /api/submissions (manager only, enforced here on the server): for the week submissions concern now (or, while that week's window has not opened yet, the week that just closed), every employee
with a status (submitted / missing / exempt), their approved leave dates (app/leave.py, empty until Issue #28), and for
those who submitted the exact shifts by day and time plus the free-text request. It never writes anything.

Counting: `total` is every employee; `submitted` have a submission; `exempt` have approved leave for the whole week and
no submission (they are NOT missing); `missing` is everyone else. Partial-week leave is only shown, it exempts nobody.
Free text is the employee's own words and is returned as data; the UI renders it as plain text.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth, clock, cycle, cycle_service, leave
from .db import AvailabilitySubmission, Shift, User, get_db


def _iso_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def build_report(db: Session, now: datetime) -> dict:
    window, state, _ = cycle_service.current(db, now)
    if state == "not_open":
        # The target week's window has not opened yet (e.g. the night after the deadline): the manager still needs the week
        # that just closed, so report on that one instead of an empty future week.
        prev = window.week_start - timedelta(days=7)
        window = cycle.submission_window(prev, cycle_service.first_publication_of(db, prev - timedelta(days=7)))
        state = cycle.window_state(window, now)
    week = window.week_start
    days = [week + timedelta(days=i) for i in range(7)]
    shifts = {s.id: s for s in db.scalars(select(Shift)).all()}
    employees = db.scalars(select(User).where(User.access_role == "employee").order_by(User.name, User.id)).all()
    subs = {s.user_id: s for s in db.scalars(select(AvailabilitySubmission).where(AvailabilitySubmission.week_start == week)).all()}
    leave_by_user = leave.approved_leave(db, week)

    rows = []
    for u in employees:
        sub = subs.get(u.id)
        leave_days = sorted(d for d in leave_by_user.get(u.id, set()) if d in set(days))
        full_week = len(leave_days) == 7
        status = "submitted" if sub is not None else ("exempt" if full_week else "missing")
        by_day: dict[date, list[dict]] = {}
        if sub is not None:
            for slot in sub.slots:
                s = shifts.get(slot.shift_id)
                if s is None:
                    continue
                by_day.setdefault(slot.day, []).append({
                    "id": s.id, "name": s.name, "start_time": s.start_time.strftime("%H:%M"), "end_time": s.end_time.strftime("%H:%M"),
                    "ends_next_day": s.end_time <= s.start_time, "_order": (s.sort_order, s.id)})
        rows.append({
            "id": u.id, "name": u.name, "status": status,
            "updated_at": _iso_utc(sub.updated_at) if sub is not None else None,
            "leave_dates": [d.isoformat() for d in leave_days], "full_week_leave": full_week,
            "days": [{"date": d.isoformat(), "shifts": [{k: v for k, v in sh.items() if k != "_order"} for sh in sorted(v, key=lambda x: x["_order"])]}
                     for d, v in sorted(by_day.items())],
            "free_text": sub.free_text if sub is not None else None,
        })
    counts = {"total": len(rows), "submitted": sum(r["status"] == "submitted" for r in rows),
              "exempt": sum(r["status"] == "exempt" for r in rows), "missing": sum(r["status"] == "missing" for r in rows)}
    return {"cycle": {"state": state, "opens_at": cycle.local(window.opens_at).isoformat(), "closes_at": cycle.local(window.closes_at).isoformat(),
                      "timezone": "Asia/Jerusalem"},
            "week": {"start": week.isoformat(), "end": (week + timedelta(days=6)).isoformat(), "days": [d.isoformat() for d in days]},
            "counts": counts, "employees": rows}


def get_submissions(user: User = Depends(auth.require_manager), db: Session = Depends(get_db)):
    return build_report(db, clock.now())


def register(app: FastAPI) -> None:
    app.add_api_route("/api/submissions", get_submissions, methods=["GET"])

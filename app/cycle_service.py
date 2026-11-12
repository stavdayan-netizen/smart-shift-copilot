"""Glue between the pure cycle rules (app/cycle.py), the clock and the database/HTTP layer.

`first_publication_of` is the seam to the schedule tables: there are no schedules yet (milestone M3), so it returns
None and only the Thursday 22:00 rule opens a window. When schedules exist, M3-3 makes it return the earliest
`published_at` of the week's published or superseded schedules; nothing else here has to change.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import clock, cycle
from .logging_setup import log_event

MESSAGES = {
    "not_open": "ההגשה לשבוע הזה עדיין לא נפתחה.",
    "closed": "ההגשה לשבוע הזה נסגרה.",
}


def first_publication_of(db: Session, week_start: date) -> datetime | None:
    """First publication time of `week_start`'s schedule. No schedules exist yet, so always None (see module doc)."""
    return None


def _lookup(db: Session) -> cycle.PublicationLookup:
    return lambda week: first_publication_of(db, week)


def current(db: Session, now: datetime | None = None) -> tuple[cycle.Window, cycle.State, datetime | None]:
    """(window, state, first publication of the preceding schedule) for the week submissions concern now."""
    now = now or clock.now()
    window = cycle.target_window(now, _lookup(db))
    published = first_publication_of(db, window.week_start - timedelta(days=7))
    return window, cycle.window_state(window, now), published


def status_payload(db: Session) -> dict:
    now = clock.now()
    window, state, published = current(db, now)

    def iso(dt: datetime) -> str:
        return cycle.local(dt).isoformat()

    return {
        "timezone": "Asia/Jerusalem",
        "now": iso(now),
        "clock_overridden": clock.is_overridden(),
        "week_start": window.week_start.isoformat(),
        "week_end": (window.week_start + timedelta(days=6)).isoformat(),
        "state": state,
        "opens_at": iso(window.opens_at),
        "closes_at": iso(window.closes_at),
        "latest_opens_at": iso(window.latest_opens_at),
        "opened_by_publication": window.opened_by_publication,
        # not open yet and the preceding schedule is unpublished: publishing it would open the window early
        "opens_early_on_publication": state == "not_open" and published is None,
        "seconds_until_opens": max(0, int((window.opens_at - now).total_seconds())) if state == "not_open" else None,
        "seconds_until_closes": max(0, int((window.closes_at - now).total_seconds())) if state != "closed" else None,
    }


def enforce_window(db: Session, week_start: date) -> cycle.Window:
    """Server-side gate for every availability write: 409 unless the week's window is open right now."""
    try:
        week_start_ok = cycle.is_week_start(week_start)
    except AttributeError:
        week_start_ok = False
    if not week_start_ok:
        raise HTTPException(400, "תאריך תחילת השבוע אינו תקין.")
    now = clock.now()
    window = cycle.submission_window(week_start, first_publication_of(db, week_start - timedelta(days=7)))
    state = cycle.window_state(window, now)
    if state != "open":
        log_event("window_rejected", "warning", week_start=week_start.isoformat(), state=state)
        raise HTTPException(409, MESSAGES[state])
    return window

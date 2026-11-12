"""The employee availability form's data and its save (spec.md section 5).

- `GET /api/availability`: what the form needs, for the signed-in employee only: the week submissions concern
  now, whether its window is open, the days and shifts, the employee's own submission, and their last closed
  week's submission (read-only). Nothing about any other employee is ever returned.
- `PUT /api/availability`: create or replace the employee's submission for a week. The employee is always the
  session's user (there is no user id in the request; unknown fields are rejected). Checked in this order:
  the window is open (409 Hebrew), the hourly save limit (429), the content (422 Hebrew, per field).
  Saved atomically with its audit row (counts only: no slots and no free text in the audit record or the logs).

Content rules: at least one slot (an employee who cannot work at all does not submit; there is no zero-shift
submission), each slot on a day of the week and an existing shift, no duplicates, free text optional and at most
1,000 characters after cleaning. There are no numeric shift-count preferences (removed 2026-11-12).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import auth, clock, cycle_service, limits
from .audit import audited, record
from .db import AvailabilitySlot, AvailabilitySubmission, Shift, User, get_db, utcnow
from .logging_setup import log_event

FREE_TEXT_MAX = 1000

MESSAGES = {
    "no_slots": "יש לבחור לפחות משמרת אחת.",
    "bad_day": "אחד מהימים שנבחרו אינו בשבוע ההגשה.",
    "bad_shift": "אחת המשמרות שנבחרו אינה קיימת.",
    "duplicate": "אחת המשמרות נבחרה יותר מפעם אחת.",
    "text_too_long": f"הבקשות ארוכות מדי. אפשר עד {FREE_TEXT_MAX:,} תווים.",
    "no_shifts": "עדיין לא הוגדרו משמרות. יש לפנות למנהל/ת.",
}


class FieldErrors(Exception):
    """A content problem in the submission: answered as 422 with a Hebrew message per field."""

    def __init__(self, errors: list[dict]):
        super().__init__("invalid submission")
        self.errors = errors


class SlotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date
    shift_id: int


class AvailabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a forged user id or any other extra field is rejected
    week_start: date
    slots: list[SlotIn] = Field(default_factory=list, max_length=200)
    free_text: str | None = Field(default=None, max_length=5000)  # loose cap; the real one is applied after cleaning


def clean_free_text(raw: str | None) -> str | None:
    """Normalise line endings, drop control characters (keeping newline and tab), trim; empty becomes None."""
    if raw is None:
        return None
    import unicodedata

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cs", "Co", "Cn"))
    text = text.strip()
    return text or None


def validate(payload: AvailabilityIn, shifts: dict[int, Shift]) -> tuple[list[tuple[date, int]], str | None]:
    errors: list[dict] = []
    week_days = {payload.week_start + timedelta(days=i) for i in range(7)}
    if not shifts:
        errors.append({"field": "slots", "message": MESSAGES["no_shifts"]})
    elif not payload.slots:
        errors.append({"field": "slots", "message": MESSAGES["no_slots"]})
    pairs: list[tuple[date, int]] = []
    seen: set[tuple[date, int]] = set()
    for slot in payload.slots:
        key = (slot.day, slot.shift_id)
        if slot.day not in week_days:
            errors.append({"field": "slots", "message": MESSAGES["bad_day"]})
        elif slot.shift_id not in shifts:
            errors.append({"field": "slots", "message": MESSAGES["bad_shift"]})
        elif key in seen:
            errors.append({"field": "slots", "message": MESSAGES["duplicate"]})
        else:
            seen.add(key)
            pairs.append(key)
    text = clean_free_text(payload.free_text)
    if text is not None and len(text) > FREE_TEXT_MAX:
        errors.append({"field": "free_text", "message": MESSAGES["text_too_long"]})
    if errors:
        unique = list({(e["field"], e["message"]): e for e in errors}.values())
        raise FieldErrors(unique)
    return sorted(pairs), text


def _iso_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize(sub: AvailabilitySubmission | None) -> dict | None:
    if sub is None:
        return None
    return {
        "week_start": sub.week_start.isoformat(),
        "slots": sorted(({"day": s.day.isoformat(), "shift_id": s.shift_id} for s in sub.slots), key=lambda s: (s["day"], s["shift_id"])),
        "free_text": sub.free_text,
        "submitted_at": _iso_utc(sub.submitted_at),
        "updated_at": _iso_utc(sub.updated_at),
    }


def _shift_json(s: Shift) -> dict:
    return {"id": s.id, "name": s.name, "start_time": s.start_time.strftime("%H:%M"), "end_time": s.end_time.strftime("%H:%M"),
            "ends_next_day": s.end_time <= s.start_time, "required_staff": s.required_staff}


def _submission(db: Session, user_id: int, week: date) -> AvailabilitySubmission | None:
    return db.scalar(select(AvailabilitySubmission).where(AvailabilitySubmission.user_id == user_id,
                                                          AvailabilitySubmission.week_start == week))


def build_payload(db: Session, user: User, now: datetime) -> dict:
    window, state, _ = cycle_service.current(db, now)
    week = window.week_start
    previous = week - timedelta(days=7)
    shifts = db.scalars(select(Shift).order_by(Shift.sort_order, Shift.id)).all()
    locked = _submission(db, user.id, previous)
    return {
        "cycle": cycle_service.status_payload(db, now),
        "week": {"start": week.isoformat(), "end": (week + timedelta(days=6)).isoformat(),
                 "days": [(week + timedelta(days=i)).isoformat() for i in range(7)]},
        "shifts": [_shift_json(s) for s in shifts],
        "editable": state == "open",
        "submission": _serialize(_submission(db, user.id, week)),
        "locked_week": None if locked is None else {"week_start": previous.isoformat(),
                                                    "week_end": (previous + timedelta(days=6)).isoformat(),
                                                    "submission": _serialize(locked)},
        "limits": {"free_text_max": FREE_TEXT_MAX, "saves_per_hour": limits.saves_per_hour(),
                   "saves_left": limits.availability_saves_left(db, user.id)},
    }


def get_availability(user: User = Depends(auth.require_employee), db: Session = Depends(get_db)):
    return build_payload(db, user, clock.now())


def put_availability(payload: AvailabilityIn, user: User = Depends(auth.require_employee), db: Session = Depends(get_db)):
    cycle_service.enforce_window(db, payload.week_start)          # 400 / 409
    limits.check_availability_save_limit(db, user.id)             # 429
    shifts = {s.id: s for s in db.scalars(select(Shift)).all()}
    pairs, text = validate(payload, shifts)                        # 422
    created = False
    for attempt in (1, 2):
        try:
            with audited(db):
                sub = _submission(db, user.id, payload.week_start)
                created = sub is None
                now = utcnow()
                if created:
                    sub = AvailabilitySubmission(user_id=user.id, week_start=payload.week_start, submitted_at=now, updated_at=now)
                    db.add(sub)
                    db.flush()
                else:
                    sub.slots.clear()
                    db.flush()                                   # delete the old slots before inserting the new ones
                sub.free_text = text
                sub.updated_at = now
                sub.slots = [AvailabilitySlot(day=d, shift_id=s) for d, s in pairs]
                record(db, actor_id=user.id, action="availability.submitted", entity="availability_submission",
                       entity_id=sub.id, after={"week_start": payload.week_start.isoformat(), "slots": len(pairs),
                                                "has_free_text": text is not None, "created": created})
            break
        except IntegrityError:                                   # two first saves at once: the second becomes an update
            db.rollback()
            if attempt == 2:
                raise
    log_event("availability_submitted", user_id=user.id, week_start=payload.week_start.isoformat(), slots=len(pairs),
              has_free_text=text is not None, free_text_len=len(text or ""), created=created)
    body = build_payload(db, user, clock.now())
    body["saved"] = True
    return body


def register(app: FastAPI) -> None:
    """Add the routes straight to the app (not through an included router) so the route-inventory test sees them."""
    app.add_api_route("/api/availability", get_availability, methods=["GET"])
    app.add_api_route("/api/availability", put_availability, methods=["PUT"])

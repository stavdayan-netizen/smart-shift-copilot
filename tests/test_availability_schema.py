"""Availability tables: uniqueness, preference checks, the 1,000-character limit, cascade (migration 0003)."""
import uuid
from datetime import date, time

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import AvailabilitySlot, AvailabilitySubmission, SessionLocal, Shift, User
from app.users import create_employee

WEEK = date(2026, 11, 29)


@pytest.fixture
def world(db):
    """An employee and two throwaway shifts; everything created here is removed afterwards."""
    user, _ = create_employee(db, f"Avail {uuid.uuid4().hex[:8]}")
    shifts = []
    for i, (a, b) in enumerate([(time(8, 0), time(16, 0)), (time(16, 0), time(0, 0))]):
        s = Shift(name=f"avail-{uuid.uuid4().hex[:8]}", start_time=a, end_time=b, sort_order=90 + i, required_staff=2)
        db.add(s)
        shifts.append(s)
    db.commit()
    yield user, shifts
    db.rollback()
    for sub in db.scalars(select(AvailabilitySubmission).where(AvailabilitySubmission.user_id == user.id)).all():
        db.delete(sub)
    db.commit()
    for s in shifts:
        db.delete(s)
    db.delete(user)
    db.commit()


def _submission(user, **kw):
    return AvailabilitySubmission(user_id=user.id, week_start=kw.pop("week", WEEK), **kw)


def test_a_submission_with_slots_round_trips(db, world):
    user, (morning, evening) = world
    sub = _submission(user, pref_min=2, pref_max=4, free_text="מעדיפה בקרים")
    sub.slots = [AvailabilitySlot(day=date(2026, 11, 29), shift_id=morning.id), AvailabilitySlot(day=date(2026, 11, 30), shift_id=evening.id)]
    db.add(sub)
    db.commit()
    back = db.get(AvailabilitySubmission, sub.id)
    assert (back.pref_min, back.pref_max, back.free_text) == (2, 4, "מעדיפה בקרים")
    assert {(s.day, s.shift_id) for s in back.slots} == {(date(2026, 11, 29), morning.id), (date(2026, 11, 30), evening.id)}


def test_preferences_and_free_text_are_optional(db, world):
    user, _ = world
    db.add(_submission(user))
    db.commit()
    got = db.scalar(select(AvailabilitySubmission).where(AvailabilitySubmission.user_id == user.id))
    assert (got.pref_min, got.pref_max, got.free_text) == (None, None, None)
    db.add(_submission(user, week=date(2026, 12, 6), pref_max=3))      # only a maximum
    db.add(_submission(user, week=date(2026, 12, 13), pref_min=1))     # only a minimum
    db.commit()


def test_one_submission_per_employee_per_week(db, world):
    user, _ = world
    db.add(_submission(user))
    db.commit()
    db.add(_submission(user))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(_submission(user, week=date(2026, 12, 6)))                    # another week is fine
    db.commit()


@pytest.mark.parametrize("kwargs", [{"pref_min": 4, "pref_max": 2}, {"pref_min": -1}, {"pref_max": -1}])
def test_invalid_preference_ranges_are_rejected_by_the_database(db, world, kwargs):
    user, _ = world
    db.add(_submission(user, **kwargs))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_free_text_limit_is_one_thousand_characters(db, world):
    user, _ = world
    db.add(_submission(user, free_text="א" * 1000))                     # Hebrew counted in characters, not bytes
    db.commit()
    db.add(_submission(user, week=date(2026, 12, 6), free_text="א" * 1001))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_slot_can_appear_once_per_submission(db, world):
    user, (morning, _) = world
    sub = _submission(user)
    sub.slots = [AvailabilitySlot(day=WEEK, shift_id=morning.id)]
    db.add(sub)
    db.commit()
    db.add(AvailabilitySlot(submission_id=sub.id, day=WEEK, shift_id=morning.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_a_submission_deletes_its_slots(db, world):
    user, (morning, evening) = world
    sub = _submission(user)
    sub.slots = [AvailabilitySlot(day=WEEK, shift_id=morning.id), AvailabilitySlot(day=WEEK, shift_id=evening.id)]
    db.add(sub)
    db.commit()
    sub_id = sub.id
    db.delete(sub)
    db.commit()
    assert db.scalar(select(AvailabilitySlot.id).where(AvailabilitySlot.submission_id == sub_id)) is None


def test_foreign_keys_hold_on_postgresql(db, world):
    from app.db import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("SQLite does not enforce foreign keys here; PostgreSQL does (and CI runs it)")
    user, _ = world
    sub = _submission(user)
    db.add(sub)
    db.commit()
    db.add(AvailabilitySlot(submission_id=sub.id, day=WEEK, shift_id=2_000_000_000))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(AvailabilitySubmission(user_id=2_000_000_000, week_start=WEEK))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_employees_are_users_with_the_employee_role(db, world):
    user, _ = world
    assert isinstance(user, User) and user.access_role == "employee"

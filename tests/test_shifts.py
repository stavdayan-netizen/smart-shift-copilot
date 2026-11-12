"""Shift definitions are database data, including shifts that end at midnight (app/shifts.py, table `shifts`)."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, Shift
from app.shifts import crosses_midnight, overlaps, shift_interval

UTC = timezone.utc
MORNING = SimpleNamespace(start_time=time(8, 0), end_time=time(16, 0))
EVENING = SimpleNamespace(start_time=time(16, 0), end_time=time(0, 0))   # ends at midnight, the following calendar day


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


@pytest.fixture
def temp_shift():
    """Create a throwaway shift row; remove it afterwards so other tests see only the seeded data."""
    created = []

    def make(start, end, staff=2):
        with SessionLocal() as s:
            shift = Shift(name=f"test-{uuid.uuid4().hex[:8]}", start_time=start, end_time=end, sort_order=99, required_staff=staff)
            s.add(shift)
            s.commit()
            created.append(shift.id)
            return shift.id

    yield make
    with SessionLocal() as s:
        for shift_id in created:
            row = s.get(Shift, shift_id)
            if row is not None:
                s.delete(row)
        s.commit()


def test_evening_16_to_midnight_ends_the_following_calendar_day():
    day = date(2026, 11, 18)
    start, end = shift_interval(EVENING, day)
    assert crosses_midnight(EVENING.start_time, EVENING.end_time)
    assert start == utc(2026, 11, 18, 14)                 # 16:00 local (+02:00)
    assert end == utc(2026, 11, 18, 22)                   # 00:00 on 19 Nov local
    assert end - start == timedelta(hours=8)
    from app.cycle import local
    assert local(end).date() == date(2026, 11, 19) and (local(end).hour, local(end).minute) == (0, 0)


def test_morning_ends_when_the_evening_starts_without_overlapping():
    day = date(2026, 11, 18)
    morning, evening = shift_interval(MORNING, day), shift_interval(EVENING, day)
    assert morning == (utc(2026, 11, 18, 6), utc(2026, 11, 18, 14))
    assert morning[1] == evening[0] and not overlaps(morning, evening)
    next_morning = shift_interval(MORNING, day + timedelta(days=1))
    assert not overlaps(evening, next_morning) and evening[1] < next_morning[0]    # midnight to 08:00 is uncovered


def test_a_shift_with_a_different_midnight_crossing_pattern_comes_from_data_not_code():
    night = SimpleNamespace(start_time=time(23, 0), end_time=time(7, 0))
    day = date(2026, 11, 18)
    assert overlaps(shift_interval(night, day), shift_interval(EVENING, day))             # 23:00-00:00 shared
    assert not overlaps(shift_interval(night, day), shift_interval(MORNING, day + timedelta(days=1)))   # ends 07:00, morning at 08:00
    assert overlaps(shift_interval(night, day), shift_interval(night, day))


def test_midnight_end_survives_a_database_round_trip(temp_shift):
    shift_id = temp_shift(time(16, 0), time(0, 0))
    with SessionLocal() as s:
        row = s.get(Shift, shift_id)
        assert (row.start_time, row.end_time) == (time(16, 0), time(0, 0))
        assert shift_interval(row, date(2026, 11, 18)) == shift_interval(EVENING, date(2026, 11, 18))


def test_overnight_shift_duration_follows_real_elapsed_time_across_dst():
    night = SimpleNamespace(start_time=time(22, 0), end_time=time(6, 0))
    autumn = shift_interval(night, date(2026, 10, 24))     # clocks go back on Sunday 25 Oct at 02:00: an hour longer
    assert autumn[1] - autumn[0] == timedelta(hours=9)
    spring = shift_interval(night, date(2026, 3, 26))      # clocks go forward on Friday 27 Mar at 02:00: an hour shorter
    assert spring[1] - spring[0] == timedelta(hours=7)
    plain = shift_interval(night, date(2026, 11, 18))
    assert plain[1] - plain[0] == timedelta(hours=8)


def test_the_demo_shifts_keep_eight_hours_on_the_dst_change_days():
    for day in (date(2026, 10, 24), date(2026, 10, 25), date(2026, 3, 26), date(2026, 3, 27), date(2026, 3, 28)):
        for shift in (MORNING, EVENING):
            start, end = shift_interval(shift, day)
            assert end - start == timedelta(hours=8), (day, shift)


def test_times_in_the_skipped_hour_do_not_raise():
    odd = SimpleNamespace(start_time=time(2, 30), end_time=time(10, 0))
    start, end = shift_interval(odd, date(2026, 3, 27))    # 02:30 does not exist on 27 Mar 2026 in Israel
    assert start < end


def test_shift_rows_enforce_their_constraints(temp_shift):
    with SessionLocal() as s:
        s.add(Shift(name=f"bad-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), end_time=time(8, 0), required_staff=2))
        with pytest.raises(IntegrityError):
            s.commit()
    with SessionLocal() as s:
        s.add(Shift(name=f"bad-{uuid.uuid4().hex[:6]}", start_time=time(8, 0), end_time=time(16, 0), required_staff=-1))
        with pytest.raises(IntegrityError):
            s.commit()
    name = f"dup-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as s:
        s.add(Shift(name=name, start_time=time(8, 0), end_time=time(16, 0)))
        s.commit()
        s.add(Shift(name=name, start_time=time(9, 0), end_time=time(17, 0)))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.query(Shift).filter_by(name=name).delete()
        s.commit()

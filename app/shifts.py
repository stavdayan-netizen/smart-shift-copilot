"""Shift time arithmetic. Shift definitions are database rows (`shifts`); nothing about a shift is hard-coded here.

A shift's `start_time` and `end_time` are wall-clock times in Asia/Jerusalem. If `end_time <= start_time` the shift
ends on the NEXT calendar day: 16:00-00:00 starts at 16:00 on day D and ends at 00:00 at the start of D+1 (eight
hours). `shift_interval` turns that into a real interval of aware UTC instants for a given day, computed from the
local dates, so it is correct across Israel's DST changes. Times that fall in the skipped or repeated hour of a DST
change follow Python's default (PEP 495, fold=0) instead of raising.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol

from .cycle import local_instant


class HasTimes(Protocol):
    start_time: time
    end_time: time


def crosses_midnight(start_time: time, end_time: time) -> bool:
    return end_time <= start_time


def shift_interval(shift: HasTimes, day: date) -> tuple[datetime, datetime]:
    """(start, end) as aware UTC instants for the shift that begins on local date `day`."""
    start = local_instant(day, shift.start_time)
    end_day = day + timedelta(days=1) if crosses_midnight(shift.start_time, shift.end_time) else day
    end = local_instant(end_day, shift.end_time)
    return start, end


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    """Half-open intervals: a shift that ends exactly when another starts does not overlap it."""
    return a[0] < b[1] and b[0] < a[1]

"""The weekly submission cycle: when the window for a workweek opens and closes. Pure, deterministic, timezone-safe.

Rules (spec.md section 4; approved 2026-11-11 and 2026-11-12). For a target workweek that starts on Sunday S:
- it **closes** on Tuesday 22:00 Asia/Jerusalem, the Tuesday 5 days before S;
- it **opens** at the *earlier* of (a) the first publication of the preceding week's schedule and (b) Thursday
  22:00 Asia/Jerusalem, the Thursday 10 days before S, even if that schedule is unpublished. With no preceding
  schedule (the first cycle) only (b) applies;
- later publications, corrections and republications never move the opening time, a late publication does not
  change an already-open window, and nothing ever extends the Tuesday deadline.

Nothing here reads the database or the clock: callers pass the instant and, if known, the first publication
time. Local wall-clock times are converted to UTC with the IANA tz database for the *local date* in question
(never by subtracting from a UTC instant), so a window that spans an Israel DST change is still Thursday 22:00 and
Tuesday 22:00 local time. Instants are returned as aware UTC datetimes; `local()` renders Asia/Jerusalem.

Boundaries: a window is open for `opens_at <= now < closes_at`; at exactly the deadline it is closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal

from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jerusalem")  # fixed by the product rules; deliberately not the TIMEZONE setting
UTC = timezone.utc
DEADLINE_TIME = time(22, 0)
CLOSE_DAYS_BEFORE = 5        # Tuesday before the target Sunday
LATEST_OPEN_DAYS_BEFORE = 10  # Thursday 10 days before the target Sunday

State = Literal["not_open", "open", "closed"]


class NotAWeekStart(ValueError):
    """A week is identified by its Sunday."""


def is_week_start(d: date) -> bool:
    return d.weekday() == 6  # Monday is 0, Sunday is 6


def week_start_of(d: date) -> date:
    """The Sunday on or before `d`."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _require_week_start(d: date) -> None:
    if not isinstance(d, date) or isinstance(d, datetime) or not is_week_start(d):
        raise NotAWeekStart(f"{d!r} is not a Sunday")


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: scheduling instants must be timezone-aware")
    return dt.astimezone(UTC)


def local_instant(day: date, at: time) -> datetime:
    """Wall-clock `at` on local date `day` in Asia/Jerusalem, as an aware UTC instant."""
    return datetime.combine(day, at, tzinfo=TZ).astimezone(UTC)


def local(dt: datetime) -> datetime:
    return _aware(dt).astimezone(TZ)


def closes_at(week_start: date) -> datetime:
    """Tuesday 22:00 local, five days before the week's Sunday."""
    _require_week_start(week_start)
    return local_instant(week_start - timedelta(days=CLOSE_DAYS_BEFORE), DEADLINE_TIME)


def latest_opens_at(week_start: date) -> datetime:
    """Thursday 22:00 local, ten days before the week's Sunday: the latest the window ever opens."""
    _require_week_start(week_start)
    return local_instant(week_start - timedelta(days=LATEST_OPEN_DAYS_BEFORE), DEADLINE_TIME)


@dataclass(frozen=True)
class Window:
    week_start: date
    opens_at: datetime
    closes_at: datetime
    latest_opens_at: datetime
    opened_by_publication: bool  # True when the first publication opened it before Thursday 22:00


def submission_window(week_start: date, preceding_first_published_at: datetime | None = None) -> Window:
    """The window for `week_start`.

    `preceding_first_published_at` is the FIRST publication time of the preceding week's schedule, or None if it
    has none (yet, or ever). A publication can only happen after the preceding week's own deadline, so an earlier
    value is impossible; it is raised to that deadline so windows never overlap.
    """
    _require_week_start(week_start)
    closes = closes_at(week_start)
    latest = latest_opens_at(week_start)
    opens, by_publication = latest, False
    if preceding_first_published_at is not None:
        floor = closes_at(week_start - timedelta(days=7))
        published = max(_aware(preceding_first_published_at), floor)
        if published < latest:
            opens, by_publication = published, True
    return Window(week_start, opens, closes, latest, by_publication)


def window_state(window: Window, now: datetime) -> State:
    now = _aware(now)
    if now < window.opens_at:
        return "not_open"
    if now < window.closes_at:
        return "open"
    return "closed"


PublicationLookup = Callable[[date], "datetime | None"]  # preceding week's Sunday -> first publication time


def target_window(now: datetime, lookup: PublicationLookup) -> Window:
    """The window submissions concern at `now`: the first upcoming workweek whose deadline has not passed.

    On Monday through Tuesday 21:59 that is next week's; after Tuesday 22:00 it is the week after (not yet open
    until Thursday 22:00 at the latest, earlier if the schedule is published).
    """
    now = _aware(now)
    base = week_start_of(now.astimezone(TZ).date())
    for weeks_ahead in (1, 2):
        week = base + timedelta(days=7 * weeks_ahead)
        window = submission_window(week, lookup(week - timedelta(days=7)))
        if window.closes_at > now:
            return window
    raise AssertionError("unreachable: the week after next always closes in the future")


class WindowNotOpen(Exception):
    def __init__(self, state: State, window: Window):
        super().__init__(f"submission window for {window.week_start} is {state}")
        self.state, self.window = state, window


def require_open(week_start: date, now: datetime, preceding_first_published_at: datetime | None = None) -> Window:
    window = submission_window(week_start, preceding_first_published_at)
    state = window_state(window, now)
    if state != "open":
        raise WindowNotOpen(state, window)
    return window

"""The submission-window rules (app/cycle.py): deterministic, timezone-safe, DST-safe, never extending the deadline."""
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import cycle
from app.cycle import NotAWeekStart, closes_at, latest_opens_at, local, submission_window, target_window, window_state

UTC = timezone.utc
JER = ZoneInfo("Asia/Jerusalem")


def utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


# ------------------------------------------------------------------ the approved example (spec.md section 4)
def test_the_approved_example_for_29_nov_to_5_dec():
    week = date(2026, 11, 29)
    assert closes_at(week) == utc(2026, 11, 24, 20)            # Tuesday 24 Nov 22:00 (+02:00)
    assert latest_opens_at(week) == utc(2026, 11, 19, 20)      # Thursday 19 Nov 22:00 (+02:00)
    # the preceding schedule (22-28 Nov, deadline Tue 17 Nov 22:00) published on Wednesday 18 Nov: opens immediately
    published = utc(2026, 11, 18, 8)                           # 10:00 local
    w = submission_window(week, published)
    assert w.opens_at == published and w.opened_by_publication and w.closes_at == utc(2026, 11, 24, 20)
    # otherwise it opens no later than Thursday 19 Nov 22:00
    w = submission_window(week, None)
    assert w.opens_at == utc(2026, 11, 19, 20) and not w.opened_by_publication
    assert local(w.opens_at).isoformat() == "2026-11-19T22:00:00+02:00"
    assert local(w.closes_at).isoformat() == "2026-11-24T22:00:00+02:00"


def test_the_preceding_weeks_own_deadline_is_tuesday_17_nov():
    assert closes_at(date(2026, 11, 22)) == utc(2026, 11, 17, 20)


# ------------------------------------------------------------------ confirmed decisions (2026-11-12)
def test_first_cycle_without_a_preceding_schedule_opens_on_the_thursday_rule():
    w = submission_window(date(2026, 11, 29), None)
    assert w.opens_at == w.latest_opens_at and not w.opened_by_publication


@pytest.mark.parametrize("offset,early", [(-timedelta(days=1), True), (-timedelta(seconds=1), True),
                                          (timedelta(0), False), (timedelta(seconds=1), False), (timedelta(days=2), False)])
def test_publication_opens_early_only_when_before_thursday_22_00(offset, early):
    week = date(2026, 11, 29)
    latest = latest_opens_at(week)
    w = submission_window(week, latest + offset)
    assert w.opened_by_publication is early
    assert w.opens_at == (latest + offset if early else latest)   # a late publication changes nothing


def test_the_deadline_is_never_extended_by_any_publication():
    week = date(2026, 11, 29)
    base = closes_at(week)
    for published in [None, utc(2026, 11, 18), utc(2026, 11, 20), utc(2026, 11, 24, 21), utc(2026, 12, 30)]:
        assert submission_window(week, published).closes_at == base


def test_a_publication_cannot_open_the_window_before_the_preceding_deadline():
    week = date(2026, 11, 29)
    floor = closes_at(date(2026, 11, 22))
    w = submission_window(week, utc(2026, 11, 10))      # impossible in the real flow; never overlaps the previous window
    assert w.opens_at == floor


def test_windows_never_overlap_the_previous_one():
    rng = random.Random(7)
    for k in range(200):
        week = date(2026, 1, 4) + timedelta(days=7 * k)
        prev = submission_window(week - timedelta(days=7), None)
        published = closes_at(week - timedelta(days=7)) + timedelta(hours=rng.randint(-100, 300))
        for p in (None, published):
            assert submission_window(week, p).opens_at >= prev.closes_at


# ------------------------------------------------------------------ timezone and DST
def test_window_spanning_the_autumn_change_is_still_thursday_and_tuesday_22_00_local():
    week = date(2026, 11, 1)   # Israel clocks go back on Sunday 25 Oct 2026 at 02:00
    assert latest_opens_at(week) == utc(2026, 10, 22, 19)   # Thursday 22:00 at +03:00
    assert closes_at(week) == utc(2026, 10, 27, 20)         # Tuesday 22:00 at +02:00
    assert local(latest_opens_at(week)).isoformat() == "2026-10-22T22:00:00+03:00"
    assert local(closes_at(week)).isoformat() == "2026-10-27T22:00:00+02:00"


def test_window_spanning_the_spring_change_is_still_thursday_and_tuesday_22_00_local():
    week = date(2026, 4, 5)    # Israel clocks go forward on Friday 27 Mar 2026 at 02:00
    assert latest_opens_at(week) == utc(2026, 3, 26, 20)    # Thursday 22:00 at +02:00
    assert closes_at(week) == utc(2026, 3, 31, 19)          # Tuesday 22:00 at +03:00
    assert local(latest_opens_at(week)).isoformat() == "2026-03-26T22:00:00+02:00"
    assert local(closes_at(week)).isoformat() == "2026-03-31T22:00:00+03:00"


def test_the_dst_assumptions_of_these_tests_match_the_tz_database():
    assert datetime(2026, 10, 22, 12, tzinfo=JER).utcoffset() == timedelta(hours=3)
    assert datetime(2026, 10, 27, 12, tzinfo=JER).utcoffset() == timedelta(hours=2)
    assert datetime(2026, 3, 26, 12, tzinfo=JER).utcoffset() == timedelta(hours=2)
    assert datetime(2026, 3, 31, 12, tzinfo=JER).utcoffset() == timedelta(hours=3)


def test_every_week_for_nine_years_closes_tuesday_22_00_and_opens_by_thursday_22_00_local():
    week = date(2024, 1, 7)
    while week < date(2033, 1, 1):
        close, latest = local(closes_at(week)), local(latest_opens_at(week))
        assert (close.weekday(), close.hour, close.minute, close.second) == (1, 22, 0, 0), week
        assert (latest.weekday(), latest.hour, latest.minute, latest.second) == (3, 22, 0, 0), week
        assert close.date() == week - timedelta(days=5) and latest.date() == week - timedelta(days=10)
        assert abs((closes_at(week) - latest_opens_at(week)) - timedelta(days=5)) <= timedelta(hours=1)
        assert latest_opens_at(week + timedelta(days=7)) >= closes_at(week)
        week += timedelta(days=7)


def test_results_do_not_depend_on_the_process_timezone(monkeypatch):
    import os
    import time as time_module

    before = (closes_at(date(2026, 11, 29)), latest_opens_at(date(2026, 11, 29)))
    if hasattr(time_module, "tzset"):
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time_module.tzset()
        try:
            assert (closes_at(date(2026, 11, 29)), latest_opens_at(date(2026, 11, 29))) == before
        finally:
            monkeypatch.undo()
            time_module.tzset()
    assert before[0].tzinfo is not None and os is not None


# ------------------------------------------------------------------ state and boundaries
def test_boundaries_to_the_second():
    w = submission_window(date(2026, 11, 29), None)
    assert window_state(w, w.opens_at - timedelta(seconds=1)) == "not_open"
    assert window_state(w, w.opens_at) == "open"
    assert window_state(w, w.closes_at - timedelta(seconds=1)) == "open"
    assert window_state(w, w.closes_at) == "closed"
    assert window_state(w, w.closes_at + timedelta(days=30)) == "closed"


def test_naive_datetimes_and_non_sundays_are_rejected():
    with pytest.raises(ValueError):
        window_state(submission_window(date(2026, 11, 29)), datetime(2026, 11, 20, 12))
    with pytest.raises(ValueError):
        submission_window(date(2026, 11, 29), datetime(2026, 11, 18, 8))
    for bad in (date(2026, 11, 30), date(2026, 11, 28), datetime(2026, 11, 29, 0, 0)):
        with pytest.raises(NotAWeekStart):
            closes_at(bad)


def test_week_start_of():
    assert cycle.week_start_of(date(2026, 11, 29)) == date(2026, 11, 29)   # Sunday
    assert cycle.week_start_of(date(2026, 12, 5)) == date(2026, 11, 29)    # Saturday
    assert cycle.week_start_of(date(2026, 11, 30)) == date(2026, 11, 29)   # Monday
    assert cycle.is_week_start(date(2026, 11, 29)) and not cycle.is_week_start(date(2026, 11, 30))


# ------------------------------------------------------------------ which week submissions concern
def no_publication(_week):
    return None


def test_target_week_through_the_cycle_of_the_example():
    # Monday 16 Nov: next workweek is 22-28 Nov, open since Thursday 12 Nov at the latest
    w = target_window(utc(2026, 11, 16, 12), no_publication)
    assert w.week_start == date(2026, 11, 22) and window_state(w, utc(2026, 11, 16, 12)) == "open"
    # one second before its deadline it is still that week; at the deadline the target moves on
    close = closes_at(date(2026, 11, 22))
    assert target_window(close - timedelta(seconds=1), no_publication).week_start == date(2026, 11, 22)
    after = target_window(close, no_publication)
    assert after.week_start == date(2026, 11, 29) and window_state(after, close) == "not_open"
    # Wednesday 18 Nov, nothing published: not open until Thursday 22:00 at the latest
    w = target_window(utc(2026, 11, 18, 7), no_publication)
    assert w.week_start == date(2026, 11, 29) and window_state(w, utc(2026, 11, 18, 7)) == "not_open"
    # the same moment with the preceding schedule published that morning: open immediately
    published = utc(2026, 11, 18, 5)
    w = target_window(utc(2026, 11, 18, 7), lambda week: published if week == date(2026, 11, 22) else None)
    assert w.week_start == date(2026, 11, 29) and window_state(w, utc(2026, 11, 18, 7)) == "open"
    # Thursday 19 Nov 22:00 local: it opens by the rule even though nothing was published
    thursday = utc(2026, 11, 19, 20)
    assert window_state(target_window(thursday, no_publication), thursday) == "open"
    assert window_state(target_window(thursday - timedelta(seconds=1), no_publication), thursday - timedelta(seconds=1)) == "not_open"


def test_target_week_invariants_over_three_years():
    rng = random.Random(11)
    start = utc(2025, 1, 1)
    for _ in range(3000):
        now = start + timedelta(seconds=rng.randint(0, 3 * 365 * 24 * 3600))
        w = target_window(now, no_publication)
        assert w.closes_at > now                                            # its deadline has not passed
        assert cycle.is_week_start(w.week_start) and w.week_start > local(now).date() - timedelta(days=1)
        assert closes_at(w.week_start - timedelta(days=7)) <= now           # the previous week's deadline has passed
        assert w.week_start - cycle.week_start_of(local(now).date()) in (timedelta(days=7), timedelta(days=14))


def test_publication_lookup_is_called_with_the_preceding_weeks_sunday():
    seen = []

    def lookup(week):
        seen.append(week)
        return None

    target_window(utc(2026, 11, 18, 7), lookup)
    assert seen and all(cycle.is_week_start(w) for w in seen)
    assert date(2026, 11, 22) in seen      # the preceding week of the 29 Nov window


def test_require_open_gates_a_write():
    week = date(2026, 11, 29)
    cycle.require_open(week, utc(2026, 11, 20, 12))
    with pytest.raises(cycle.WindowNotOpen) as info:
        cycle.require_open(week, utc(2026, 11, 18, 12))
    assert info.value.state == "not_open"
    with pytest.raises(cycle.WindowNotOpen) as info:
        cycle.require_open(week, closes_at(week))
    assert info.value.state == "closed"
    cycle.require_open(week, utc(2026, 11, 18, 12), preceding_first_published_at=utc(2026, 11, 18, 5))

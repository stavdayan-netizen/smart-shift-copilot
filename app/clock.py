"""The one place the application asks what time it is for scheduling rules.

`now()` returns a timezone-aware UTC datetime. In production it is the real clock. Outside production a
`CLOCK_OVERRIDE` (an ISO-8601 instant with a UTC offset) freezes it at that instant, so the submission window and
the Tuesday deadline can be tested and demonstrated; the application refuses to start with the variable set in
production (app/config.py). A frozen clock is deterministic and identical in every process (web and cron).

Only the scheduling cycle (app/cycle.py) and what shows it use this clock. Logs, rate limits, session expiry and
cost accounting keep using the real time on purpose, so an overridden demo clock can never hide real events.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import settings


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


_override: datetime | None = _parse(settings.clock_override)


def is_overridden() -> bool:
    return _override is not None


def now() -> datetime:
    """The current instant, aware, in UTC."""
    return _override if _override is not None else datetime.now(timezone.utc)

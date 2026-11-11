"""The daily digest (infrastructure kept from the instructor; content is generic for now).

Runs as a Railway cron service (`python -m app.digest`, schedule in README.md)
or through POST /internal/digest. It only reads. The Smart Shift brief (M6-1)
replaces the content; it stays deterministic and makes no model call.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Message, Run, SessionLocal
from .logging_setup import configure_logging, log_event


def _local_bounds(day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def build_digest(db: Session, day: date | None = None) -> str:
    tz = ZoneInfo(settings.timezone)
    day = day or (datetime.now(tz).date() - timedelta(days=1))
    start, end = _local_bounds(day)

    messages = db.scalar(select(func.count()).select_from(Message)
                         .where(Message.role == "user", Message.created_at >= start, Message.created_at < end)) or 0
    runs = db.execute(select(func.count(Run.id), func.coalesce(func.sum(Run.cost_usd), 0.0),
                             func.sum(case((Run.status != "ok", 1), else_=0)))
                      .where(Run.created_at >= start, Run.created_at < end)).one()
    run_count, cost, not_ok = int(runs[0] or 0), float(runs[1] or 0.0), int(runs[2] or 0)

    lines = [f"Smart Shift Copilot — {day.strftime('%A %d %b %Y')}",
             f"Chat: {messages} messages · {run_count} model runs · ${cost:.2f} of ${settings.daily_cap_usd:.2f} cap",
             f"Runs not OK: {not_ok}" + (" — check the runs table and runbook.md" if not_ok else "")]
    return "\n".join(lines)


def send_digest(text: str) -> bool:
    """POST {"text": ...} to DIGEST_WEBHOOK_URL (Slack-compatible). Returns False when no URL is set."""
    if not settings.digest_webhook_url:
        return False
    import httpx

    r = httpx.post(settings.digest_webhook_url, json={"text": text}, timeout=15)
    r.raise_for_status()
    return True


def main() -> None:
    configure_logging(settings.log_level)
    with SessionLocal() as db:
        body = build_digest(db)
    print(body)  # the digest text is the job's output, not a log line
    sent = send_digest(body)
    log_event("digest_run", sent=sent, lines=len(body.splitlines()))


if __name__ == "__main__":
    main()

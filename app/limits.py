"""The limits from architecture.md: per user per hour and per day in money. (The per-minute limit towards Anthropic is
handled by the SDK's retries plus the backoff in agent.py.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import AuditLog, Message, Run, utcnow


def local_day_start_utc(now_utc: datetime | None = None) -> datetime:
    """Midnight today in the business timezone, expressed in naive UTC (how we store)."""
    tz = ZoneInfo(settings.timezone)
    now_utc = now_utc or utcnow()
    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def messages_last_hour(db: Session, user_id: int) -> int:
    since = utcnow() - timedelta(hours=1)
    return int(db.scalar(select(func.count()).select_from(Message)
                         .where(Message.user_id == user_id, Message.role == "user", Message.created_at >= since)) or 0)


def spend_today_usd(db: Session) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(Run.cost_usd), 0.0)).where(Run.created_at >= local_day_start_utc())) or 0.0)


def check_rate_limit(db: Session, user_id: int) -> None:
    used = messages_last_hour(db, user_id)
    if used >= settings.rate_limit_per_hour:
        raise HTTPException(429, f"שלחתם {used} הודעות בשעה האחרונה, והמגבלה היא {settings.rate_limit_per_hour}. אפשר לנסות שוב מאוחר יותר.")


def check_daily_cap(db: Session) -> None:
    spent = spend_today_usd(db)
    if spent >= settings.daily_cap_usd:
        raise HTTPException(402, f"תקציב היום (${settings.daily_cap_usd:.2f}) נוצל. אפשר לנסות שוב מחר.")


# ---------------------------------------------------------------------------
# Availability saves: a small per-employee limit (default 20 per hour), counted from the audit records of
# successful saves (counts only, see app/availability.py), so it needs no extra table and survives restarts.
# ---------------------------------------------------------------------------

def saves_per_hour() -> int:
    return settings.availability_saves_per_hour


def _recent_saves(db: Session, user_id: int, now: datetime) -> list[datetime]:
    return list(db.scalars(select(AuditLog.at).where(AuditLog.actor_id == user_id, AuditLog.action == "availability.submitted",
                                                     AuditLog.at >= now - timedelta(hours=1))
                           .order_by(AuditLog.at.desc()).limit(saves_per_hour())).all())


def availability_saves_left(db: Session, user_id: int, now: datetime | None = None) -> int:
    return max(0, saves_per_hour() - len(_recent_saves(db, user_id, now or utcnow())))


def check_availability_save_limit(db: Session, user_id: int, now: datetime | None = None) -> None:
    now = now or utcnow()
    recent = _recent_saves(db, user_id, now)
    if len(recent) >= saves_per_hour():
        wait = max(1, int((recent[-1] + timedelta(hours=1) - now).total_seconds()))
        minutes = max(1, round(wait / 60))
        when = "בעוד דקה" if minutes == 1 else f"בעוד {minutes} דקות"
        raise HTTPException(429, f"בוצעו {saves_per_hour()} שמירות בשעה האחרונה, וזו המגבלה. אפשר לנסות שוב {when}.",
                            headers={"Retry-After": str(wait)})

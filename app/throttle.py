"""Login throttling kept in the database, so it survives restarts and works with any number of app processes.

One table (`login_throttle`) holds counters for two kinds of keys:
- `name`: the attempted account name, whether or not such an account exists. Unknown names are
  counted and locked exactly like real ones, so a response never reveals which names exist;
- `ip`: the client address, enabled only when a trustworthy client IP is available (see client_ip()).

Keys are HMACs of the name or address under APP_SECRET, so the table holds no names or addresses.
After THRESHOLD consecutive failures a key is locked for BASE seconds, doubling with each further
failure up to CAP. A success clears the account's counter. Counters older than DECAY are forgotten,
and idle rows are deleted on the way.

Every function commits its own small transaction and increments atomically in SQL, so two
processes cannot lose each other's updates.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
from datetime import timedelta

from fastapi import Request
from sqlalchemy import case, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import LoginThrottle, utcnow

NAME_POLICY = {"threshold": 5, "base": 60, "cap": 900}
IP_POLICY = {"threshold": 20, "base": 300, "cap": 900}
DECAY = timedelta(hours=1)
PURGE_AFTER = timedelta(days=1)


def now():
    return utcnow()


def _key(kind: str, value: str) -> str:
    return hmac.new(settings.app_secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:32]


def name_key(name: str) -> str:
    return _key("name", " ".join((name or "").split()).lower()[:80])


def ip_key(ip: str) -> str:
    return _key("ip", ip)


def ip_throttle_enabled() -> bool:
    """Without a verified client-IP source behind a proxy, every user would share one address and a
    single attacker could lock everybody out, so in production the per-IP limit is off unless
    CLIENT_IP_HEADER is configured."""
    return bool(settings.client_ip_header) or not settings.is_production


def client_ip(request: Request) -> str:
    """The configured trusted header if set and valid, else the socket peer. Never a header by default."""
    header = settings.client_ip_header
    if header:
        raw = request.headers.get(header, "")
        candidate = raw.split(",")[-1].strip() if raw else ""  # the entry our own proxy appended
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def blocked_for(db: Session, keys: list[str]) -> int:
    """Seconds until the longest lock among `keys` ends; 0 if none is locked."""
    t = now()
    until = db.scalars(select(LoginThrottle.locked_until).where(LoginThrottle.key.in_(keys),
                                                                 LoginThrottle.locked_until > t)).all()
    return max((math.ceil((u - t).total_seconds()) for u in until), default=0)


def record_failure(db: Session, key: str, *, threshold: int, base: int, cap: int) -> int:
    """Count one failure atomically; lock the key when the threshold is reached. Returns the failure count."""
    t = now()
    stale = t - DECAY
    bump = update(LoginThrottle).where(LoginThrottle.key == key).values(
        failures=case((LoginThrottle.updated_at < stale, 1), else_=LoginThrottle.failures + 1), updated_at=t
    ).returning(LoginThrottle.failures)
    row = db.execute(bump).first()
    if row is None:
        try:
            db.execute(insert(LoginThrottle).values(key=key, failures=1, updated_at=t))
            failures = 1
        except IntegrityError:  # another process created it first
            db.rollback()
            failures = db.execute(bump).scalar_one()
    else:
        failures = row[0]
    if failures >= threshold:
        delay = min(base * 2 ** (failures - threshold), cap)
        db.execute(update(LoginThrottle).where(LoginThrottle.key == key).values(locked_until=t + timedelta(seconds=delay)))
    db.execute(delete(LoginThrottle).where(LoginThrottle.updated_at < t - PURGE_AFTER,
                                           (LoginThrottle.locked_until.is_(None)) | (LoginThrottle.locked_until < t)))
    db.commit()
    return failures


def record_success(db: Session, key: str) -> None:
    db.execute(delete(LoginThrottle).where(LoginThrottle.key == key))
    db.commit()

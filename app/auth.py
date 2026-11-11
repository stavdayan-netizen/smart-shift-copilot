"""Shared-password login with a signed cookie. Ten staff, one business (spec.md §1).

Not a user-management system: everyone knows the one password and types their
own name, which becomes their user row for history and rate limits.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import re
import time

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import User
from .logging_setup import log_event

COOKIE_NAME = "bc_session"
_NAME_RE = re.compile(r"^[\w .'\-֐-׿]{2,40}$")  # latin, digits, Hebrew letters


def password_ok(candidate: str) -> bool:
    return hmac.compare_digest((candidate or "").encode(), settings.app_password.encode())


def normalise_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not _NAME_RE.match(name):
        raise HTTPException(400, "Name must be 2-40 letters, digits or spaces.")
    return name


def _sign(payload: bytes) -> bytes:
    # Hex, not the raw digest: raw bytes can include the "|" that separates the
    # signature from the payload, and such a token would never read back (ticket 25).
    return hmac.new(settings.app_secret.encode(), payload, hashlib.sha256).hexdigest().encode()


def make_token(user_id: int, name: str) -> str:
    exp = int(time.time()) + settings.session_hours * 3600
    payload = f"{user_id}|{name}|{exp}".encode()
    return base64.urlsafe_b64encode(payload + b"|" + _sign(payload)).decode()


def read_token(token: str | None) -> tuple[int, str] | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        payload, sig = raw.rsplit(b"|", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        user_id, name, exp = payload.decode().split("|")
        if int(exp) < time.time():
            return None
        return int(user_id), name
    except Exception:
        return None


def get_or_create_user(db: Session, name: str) -> User:
    user = db.scalar(select(User).where(User.name == name))
    if user is None:
        user = User(name=name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def current_user(request: Request, db: Session) -> User:
    parsed = read_token(request.cookies.get(COOKIE_NAME))
    if parsed is None:
        log_event("auth_failed", reason="no_valid_session")
        raise HTTPException(401, "Please sign in.")
    user = db.get(User, parsed[0])
    if user is None:
        log_event("auth_failed", "warning", reason="unknown_user_in_session")
        raise HTTPException(401, "Please sign in.")
    return user

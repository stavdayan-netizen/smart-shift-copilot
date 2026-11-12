"""Sessions, login and the authorization dependencies.

Login is a name plus a personal access code (employees) or the manager password (from the
environment). Accounts are created by an operator (app/users.py); there is no self-registration.

Session: a signed cookie holding `user_id|token_version|expiry`. The role is never read from the
cookie: it is looked up in the database on every request. Bumping a user's `token_version`
(rotating a code, changing the manager password) invalidates all of that user's sessions.

Authorization is enforced here, on the backend, by dependencies every non-public route must declare:
    require_user      any signed-in account
    require_employee  employees only (the employee id always comes from the session, never from a request)
    require_manager   the manager only (Copilot, dashboards, approvals)
Order of answers: no/invalid session -> 401, wrong role -> 403, someone else's record -> 404 (owned_or_404).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import passwords, throttle
from .audit import audited, record
from .config import settings
from .db import User, get_db
from .logging_setup import log_event

COOKIE_NAME = "shift_session"
GENERIC_FAILURE = "השם או קוד הגישה שגויים."
SIGN_IN_REQUIRED = "נדרשת התחברות."
_NAME_RE = re.compile(r"^[\w .'\-֐-׿]{2,40}$")  # latin, digits, Hebrew letters


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

def _sign(payload: bytes) -> bytes:
    # Hex, not the raw digest: raw bytes can include the "|" that separates the signature (ticket 25).
    return hmac.new(settings.app_secret.encode(), payload, hashlib.sha256).hexdigest().encode()


def make_token(user_id: int, token_version: int) -> str:
    exp = int(time.time()) + settings.session_hours * 3600
    payload = f"{user_id}|{token_version}|{exp}".encode()
    return base64.urlsafe_b64encode(payload + b"|" + _sign(payload)).decode()


def read_token(token: str | None) -> tuple[int, int] | None:
    """(user_id, token_version) if the signature is valid and the token has not expired."""
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        payload, sig = raw.rsplit(b"|", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        user_id, version, exp = payload.decode().split("|")
        if int(exp) < time.time():
            return None
        return int(user_id), int(version)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def authenticate(db: Session, request: Request, name: str, code: str) -> User:
    """Check a login attempt. Every failure is the same 401; locks are the same 429 for real and unknown names."""
    normalised = " ".join((name or "").split())
    nkey = throttle.name_key(normalised)
    ikey = throttle.ip_key(throttle.client_ip(request)) if throttle.ip_throttle_enabled() else None

    wait_name = throttle.blocked_for(db, [nkey])
    wait_ip = throttle.blocked_for(db, [ikey]) if ikey else 0
    if wait_name or wait_ip:
        wait = max(wait_name, wait_ip)
        log_event("login_blocked", "warning", scope=[s for s, w in (("name", wait_name), ("ip", wait_ip)) if w],
                  retry_after=wait)
        minutes = max(1, round(wait / 60))
        when = "בעוד דקה" if minutes == 1 else f"בעוד {minutes} דקות"
        raise HTTPException(429, f"יותר מדי ניסיונות כושלים. אפשר לנסות שוב {when}.",
                            headers={"Retry-After": str(wait)})

    user = db.scalar(select(User).where(User.name == normalised)) if _NAME_RE.match(normalised) else None
    # The manager password is used as typed; employee codes are normalised (case, dashes, spaces).
    secret = code if (user is not None and user.access_role == "manager") else passwords.normalize_code(code)
    ok = passwords.verify_secret(secret, user.code_hash if user is not None else None)  # unknown name: dummy work
    if user is None or not ok:
        throttle.record_failure(db, nkey, **throttle.NAME_POLICY)
        if ikey:
            throttle.record_failure(db, ikey, **throttle.IP_POLICY)
        log_event("auth_failed", "warning", reason="bad_credentials", user_id=user.id if user is not None else None)
        raise HTTPException(401, GENERIC_FAILURE)
    throttle.record_success(db, nkey)
    log_event("login_succeeded", user_id=user.id, role=user.access_role)
    return user


# ---------------------------------------------------------------------------
# Authorization dependencies
# ---------------------------------------------------------------------------

def current_user(request: Request, db: Session) -> User:
    parsed = read_token(request.cookies.get(COOKIE_NAME))
    if parsed is None:
        log_event("auth_failed", reason="no_valid_session")
        raise HTTPException(401, SIGN_IN_REQUIRED)
    user = db.get(User, parsed[0])
    if user is None:
        log_event("auth_failed", "warning", reason="unknown_user_in_session")
        raise HTTPException(401, SIGN_IN_REQUIRED)
    if user.token_version != parsed[1]:
        log_event("auth_failed", reason="stale_session", user_id=user.id)
        raise HTTPException(401, SIGN_IN_REQUIRED)
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    return current_user(request, db)


def _require_role(role: str, request: Request, user: User) -> User:
    if user.access_role != role:
        log_event("forbidden", "warning", user_id=user.id, required=role, actual=user.access_role,
                  method=request.method)
        raise HTTPException(403, "אין הרשאה לפעולה הזו.")
    return user


def require_employee(request: Request, user: User = Depends(require_user)) -> User:
    return _require_role("employee", request, user)


def require_manager(request: Request, user: User = Depends(require_user)) -> User:
    return _require_role("manager", request, user)


# Read by the route-inventory test: every non-public route must depend on one of these.
require_user.auth_level = "user"  # type: ignore[attr-defined]
require_employee.auth_level = "employee"  # type: ignore[attr-defined]
require_manager.auth_level = "manager"  # type: ignore[attr-defined]


def owned_or_404(obj: Any, user: User, owner_attr: str = "user_id") -> Any:
    """Return `obj` only if it belongs to `user`; otherwise 404, so another person's record looks nonexistent."""
    if obj is None or getattr(obj, owner_attr, None) != user.id:
        raise HTTPException(404, "לא נמצא.")
    return obj


# ---------------------------------------------------------------------------
# Manager bootstrap (startup)
# ---------------------------------------------------------------------------

def ensure_manager(db: Session) -> str:
    """Create the manager account from MANAGER_NAME/MANAGER_PASSWORD, or follow a changed password.

    Returns "disabled", "created", "updated" or "unchanged". A changed password bumps token_version,
    so old manager sessions stop working. Both outcomes are audited (no secrets in the record).
    """
    if not settings.manager_password:
        return "disabled"
    user = db.scalar(select(User).where(User.name == settings.manager_name))
    if user is not None and user.access_role != "manager":
        raise RuntimeError("MANAGER_NAME matches an existing employee account; choose another name.")
    if user is None:
        try:
            with audited(db):
                user = User(name=settings.manager_name, access_role="manager",
                            code_hash=passwords.hash_secret(settings.manager_password))
                db.add(user)
                db.flush()
                record(db, actor_id=None, action="user.manager_created", entity="user", entity_id=user.id,
                       after={"name": user.name, "access_role": "manager"})
            return "created"
        except IntegrityError:  # another process created it at the same moment
            db.rollback()
            user = db.scalar(select(User).where(User.name == settings.manager_name))
            if user is None:
                raise
    if passwords.verify_secret(settings.manager_password, user.code_hash):
        return "unchanged"
    with audited(db):
        user.code_hash = passwords.hash_secret(settings.manager_password)
        user.token_version += 1
        record(db, actor_id=None, action="user.manager_password_changed", entity="user", entity_id=user.id,
               after={"name": user.name})
    return "updated"

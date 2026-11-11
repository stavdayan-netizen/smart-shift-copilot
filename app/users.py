"""Operator tool for employee accounts: create, rotate a code, list. Run locally against the target database.

    python -m app.users create "Noa Levi"      # prints the access code ONCE
    python -m app.users rotate "Noa Levi"      # new code; the old one and all sessions stop working
    python -m app.users list                   # names and roles only; codes cannot be shown (only hashes exist)

The access code is printed to the operator's terminal only. It is never logged, never written to the
audit record, and never stored: only its scrypt hash is. Employee administration screens for the
manager are a Phase 2 feature; the manager account comes from MANAGER_NAME / MANAGER_PASSWORD.
"""
from __future__ import annotations

import argparse
import re
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import passwords
from .audit import audited, record
from .db import SessionLocal, User
from .logging_setup import configure_logging, log_event

_NAME_RE = re.compile(r"^[\w .'\-֐-׿]{2,40}$")


class UserError(ValueError):
    pass


def create_employee(db: Session, name: str, *, role: str = "employee") -> tuple[User, str]:
    """Create an account and return it with its one-time code. `role` is for tests and bootstrap code."""
    name = " ".join((name or "").split())
    if not _NAME_RE.match(name):
        raise UserError("Name must be 2-40 letters, digits or spaces.")
    if db.scalar(select(User.id).where(func.lower(User.name) == name.lower())) is not None:
        raise UserError("An account with that name already exists.")
    code = passwords.generate_code()
    with audited(db):
        user = User(name=name, access_role=role, code_hash=passwords.hash_secret(passwords.normalize_code(code)))
        db.add(user)
        db.flush()
        record(db, actor_id=None, action="user.created", entity="user", entity_id=user.id,
               after={"name": user.name, "access_role": role})
    log_event("user_created", user_id=user.id, role=role)
    return user, code


def rotate_code(db: Session, name: str) -> tuple[User, str]:
    """Issue a new code for an employee and sign them out everywhere. The manager password lives in the environment."""
    user = db.scalar(select(User).where(User.name == " ".join((name or "").split())))
    if user is None:
        raise UserError("No such account.")
    if user.access_role == "manager":
        raise UserError("The manager password is changed through MANAGER_PASSWORD, not here.")
    code = passwords.generate_code()
    with audited(db):
        user.code_hash = passwords.hash_secret(passwords.normalize_code(code))
        user.token_version += 1
        record(db, actor_id=None, action="user.code_rotated", entity="user", entity_id=user.id,
               after={"name": user.name})
    log_event("user_code_rotated", user_id=user.id)
    return user, code


def list_users(db: Session) -> list[dict]:
    return [{"id": u.id, "name": u.name, "role": u.access_role, "has_code": bool(u.code_hash)}
            for u in db.scalars(select(User).order_by(User.id)).all()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.users", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("create", "rotate"):
        sub.add_parser(cmd).add_argument("name")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        try:
            if args.command == "list":
                for u in list_users(db):
                    print(f"{u['id']:>3}  {u['role']:<9} {u['name']}" + ("" if u["has_code"] else "  (no code)"))
                return 0
            user, code = (create_employee if args.command == "create" else rotate_code)(db, args.name)
        except UserError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"{user.name}: access code (shown once, store it safely): {code}")
    return 0


if __name__ == "__main__":
    configure_logging("WARNING")  # keep the terminal clean: the access code is the only output
    raise SystemExit(main())

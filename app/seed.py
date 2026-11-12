"""Seed the fictional demo data: two shifts and eight fictional employees. Idempotent and non-destructive.

    python -m app.seed                       # local or test databases
    python -m app.seed --confirm-fictional   # required when APP_ENV=production (the Railway demo)

- Shifts: missing ones are created from DEMO_SHIFTS; a shift that already exists (matched by name) is **never**
  modified, so settings changed later (times, staffing) survive every re-run. The constants below are only the
  starting values; the database rows are the configuration.
- Employees: missing ones are created with a fresh access code, printed ONCE on this terminal; existing employees
  are left alone (no new code; use `python -m app.users rotate` for that). Codes are never logged, audited or stored.
- Every creation writes an audit row in the same transaction. The employees are fictional first names only.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audited, record
from .config import settings
from .db import SessionLocal, Shift, User
from .logging_setup import configure_logging, log_event
from .users import create_employee

# name, start, end (an end at or before the start means the next calendar day), sort order, required staff
DEMO_SHIFTS = [
    ("בוקר", time(8, 0), time(16, 0), 1, 2),
    ("ערב", time(16, 0), time(0, 0), 2, 2),
]
DEMO_EMPLOYEES = ["דנה", "מיכל", "רון", "נועה", "יובל", "תמר", "אורי", "שירה"]


@dataclass
class SeedResult:
    shifts_created: list[str] = field(default_factory=list)
    shifts_existing: list[str] = field(default_factory=list)
    employees_created: list[tuple[str, str]] = field(default_factory=list)  # (name, one-time code)
    employees_existing: list[str] = field(default_factory=list)


def seed_shifts(db: Session, result: SeedResult) -> None:
    for name, start, end, order, staff in DEMO_SHIFTS:
        if db.scalar(select(Shift.id).where(Shift.name == name)) is not None:
            result.shifts_existing.append(name)  # left exactly as it is
            continue
        with audited(db):
            shift = Shift(name=name, start_time=start, end_time=end, sort_order=order, required_staff=staff)
            db.add(shift)
            db.flush()
            record(db, actor_id=None, action="shift.created", entity="shift", entity_id=shift.id,
                   after={"name": name, "start_time": start.isoformat(), "end_time": end.isoformat(),
                          "sort_order": order, "required_staff": staff})
        result.shifts_created.append(name)


def seed_employees(db: Session, result: SeedResult) -> None:
    for name in DEMO_EMPLOYEES:
        if db.scalar(select(User.id).where(User.name == name)) is not None:
            result.employees_existing.append(name)
            continue
        _, code = create_employee(db, name)  # audited inside
        result.employees_created.append((name, code))


def run_seed(db: Session) -> SeedResult:
    result = SeedResult()
    seed_shifts(db, result)
    seed_employees(db, result)
    log_event("seed_run", shifts_created=len(result.shifts_created), shifts_existing=len(result.shifts_existing),
              employees_created=len(result.employees_created), employees_existing=len(result.employees_existing))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__.split("\n\n")[0])
    parser.add_argument("--confirm-fictional", action="store_true",
                        help="required in production: confirms this database holds only fictional demo data")
    args = parser.parse_args(argv)
    if settings.is_production and not args.confirm_fictional:
        print("error: APP_ENV=production; pass --confirm-fictional to seed fictional demo data", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        result = run_seed(db)
    print(f"shifts: {len(result.shifts_created)} created, {len(result.shifts_existing)} already present (left untouched)")
    print(f"employees: {len(result.employees_created)} created, {len(result.employees_existing)} already present")
    if result.employees_created:
        print("\nAccess codes (shown once; store them safely, they cannot be shown again):")
        for name, code in result.employees_created:
            print(f"  {name}: {code}")
    return 0


if __name__ == "__main__":
    configure_logging("WARNING")
    raise SystemExit(main())

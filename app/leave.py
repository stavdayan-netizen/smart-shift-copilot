"""Approved leave: the seam the submissions report reads (Issue #28 will fill it).

Leave management (requests, manager decisions, employee acceptance) is not built yet and no leave data exists, so
`approved_leave` returns nothing. When Issue #28 adds the data, only this function changes: it must return, for the
given week, the dates of APPROVED leave per employee id (pending, rejected or proposed leave never counts). The
report (app/submissions.py) already shows partial-week leave and treats full-week leave as an exemption from
submitting. Nothing here invents data.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session


def approved_leave(db: Session, week_start: date) -> dict[int, set[date]]:
    """{employee id: dates of approved leave within week_start..week_start+6}. Empty until Issue #28."""
    return {}

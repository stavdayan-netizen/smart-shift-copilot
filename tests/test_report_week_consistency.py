"""The manager's report week and deadline match the real submission cycle, including demo clock overrides."""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import agent, clock
from app.db import SessionLocal
from app.main import app
from app.tools import shift_tools
from app.users import create_employee

H = {"X-Requested-With": "shift-copilot"}

# (frozen instant, week the manager reviews, that week's deadline, state, does an employee's form target the same week?)
CASES = [
    ("2026-11-22T12:00:00+02:00", "2026-11-29", "2026-11-24T22:00:00+02:00", "open", True),     # Sunday: next week's window is open
    ("2026-11-17T21:59:30+02:00", "2026-11-22", "2026-11-17T22:00:00+02:00", "open", True),     # 30 seconds before a deadline
    ("2026-11-17T22:00:00+02:00", "2026-11-22", "2026-11-17T22:00:00+02:00", "closed", False),  # exactly at the deadline
    ("2026-11-25T12:00:00+02:00", "2026-11-29", "2026-11-24T22:00:00+02:00", "closed", False),  # after it, next window not open yet
    ("2026-11-26T21:59:59+02:00", "2026-11-29", "2026-11-24T22:00:00+02:00", "closed", False),  # one second before the next opening
    ("2026-11-26T22:00:00+02:00", "2026-12-06", "2026-12-01T22:00:00+02:00", "open", True),     # the next window opens (Thursday 22:00)
    ("2027-03-28T12:00:00+03:00", "2027-04-04", "2027-03-30T22:00:00+03:00", "open", True),     # after the Israeli DST change (deadline at UTC+3)
]


def _manager():
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": "boss", "code": "test-manager-password"}).status_code == 200
    return c


def _same_instant(a: str, b: str) -> bool:
    return datetime.fromisoformat(a.replace("Z", "+00:00")) == datetime.fromisoformat(b)


@pytest.mark.parametrize("now,week,closes,state,employee_same", CASES)
def test_report_tool_prompt_and_form_agree_with_the_cycle(monkeypatch, db, now, week, closes, state, employee_same):
    monkeypatch.setattr(clock, "_override", datetime.fromisoformat(now).astimezone(timezone.utc))
    rep = _manager().get("/api/submissions").json()
    assert rep["week"]["start"] == week and rep["cycle"]["state"] == state
    assert _same_instant(rep["cycle"]["closes_at"], closes)
    # the Copilot's default week, deadline and prompt are the report's
    tool = shift_tools.get_submission_status(db, {})
    assert tool["week_start"] == week and tool["window_state"] == state and _same_instant(tool["closes_at"], closes)
    prompt = agent.build_system(db)[0]["text"]
    assert f"is {week} (Sunday)" in prompt and f'"{state}"' in prompt
    # the employee's own form targets the same week whenever its window is open
    user, code = create_employee(db, f"Emp{uuid.uuid4().hex[:8]}")
    e = TestClient(app, headers=H)
    assert e.post("/api/login", json={"name": user.name, "code": code}).status_code == 200
    form = e.get("/api/availability").json()
    if employee_same:
        assert form["week"]["start"] == week and form["editable"] is True and _same_instant(form["cycle"]["closes_at"], closes)
    else:
        assert form["editable"] is False and form["week"]["start"] != week     # the form already looks at the next, not yet open, week


def test_the_cycle_api_and_the_report_agree_under_a_frozen_clock(monkeypatch, db):
    monkeypatch.setattr(clock, "_override", datetime(2026, 11, 22, 10, tzinfo=timezone.utc))
    user, code = create_employee(db, f"Cyc{uuid.uuid4().hex[:8]}")
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": user.name, "code": code}).status_code == 200
    cyc = c.get("/api/cycle").json()
    rep = _manager().get("/api/submissions").json()
    assert cyc["clock_overridden"] is True
    assert cyc["week_start"] == rep["week"]["start"] and _same_instant(cyc["closes_at"], rep["cycle"]["closes_at"])

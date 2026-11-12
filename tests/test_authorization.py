"""Authorization: every route is protected on the backend, roles are enforced, people cannot see each other's data."""
import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import auth
from app.db import Conversation, Message, Run, SessionLocal, User, get_db
from app.main import app
from app.passwords import hash_secret
from app.users import create_employee

H = {"X-Requested-With": "shift-copilot"}

# Routes that are public on purpose. Everything else must declare an auth dependency.
PUBLIC = {
    ("GET", "/"),                   # the static page itself
    ("GET", "/health"),             # Railway's health check
    ("POST", "/api/login"),         # rate limited and locked out (tests/test_lockout.py)
    ("POST", "/api/logout"),        # clearing a cookie needs no identity
    ("POST", "/internal/digest"),   # authenticated by X-Cron-Secret, not a session
}


def _levels(dependant, found=None):
    found = [] if found is None else found
    for d in dependant.dependencies:
        level = getattr(d.call, "auth_level", None)
        if level:
            found.append(level)
        _levels(d, found)
    return found


def _routes():
    out = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                out.append((method, route.path, route))
    return out


def test_every_route_is_public_on_purpose_or_declares_authorization():
    unprotected = [(m, p) for m, p, r in _routes() if (m, p) not in PUBLIC and not _levels(r.dependant)]
    assert unprotected == [], f"routes without an auth dependency: {unprotected}"


def test_public_routes_stay_the_documented_few():
    declared = {(m, p) for m, p, _ in _routes()}
    assert PUBLIC <= declared, "an allow-listed route disappeared; update PUBLIC"
    leaked = [(m, p) for m, p, r in _routes() if (m, p) in PUBLIC and _levels(r.dependant)]
    assert leaked == []


def test_only_known_non_api_routes_exist():
    others = [r for r in app.routes if not isinstance(r, APIRoute)]
    assert {getattr(r, "name", None) for r in others} == {"static"}  # the mounted static files; docs are disabled


def test_copilot_and_manager_routes_require_the_manager_role():
    manager_only = {p for m, p, r in _routes() if "manager" in _levels(r.dependant)}
    assert {"/api/chat", "/api/stats", "/api/conversations", "/api/conversations/{conversation_id}/messages"} <= manager_only


def _sample(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def _call(c, method, path):
    body = {"message": "hello"} if path == "/api/chat" else ({"week_start": "2026-11-29", "slots": []} if path == "/api/availability" else None)
    return c.request(method, _sample(path), json=body, headers=H)


def _employee_client(db, name):
    user, code = create_employee(db, name)
    c = TestClient(app, headers=H)
    assert c.post("/api/login", json={"name": name, "code": code}).status_code == 200
    return c, user


def test_route_matrix_anonymous_employee_and_manager(client, db, logged_in):
    employee, _ = _employee_client(db, "Matrix Employee")
    anonymous = TestClient(app, headers=H)
    for method, path, route in _routes():
        if (method, path) in PUBLIC:
            continue
        level = _levels(route.dependant)
        assert _call(anonymous, method, path).status_code == 401, f"{method} {path} must reject anonymous"
        emp = _call(employee, method, path).status_code
        mgr = _call(client, method, path).status_code
        if "manager" in level:
            assert emp == 403, f"{method} {path} must be manager-only"
            assert mgr not in (401, 403), f"{method} {path} must allow the manager"
        elif "employee" in level:
            assert mgr == 403, f"{method} {path} must be employee-only"
            assert emp not in (401, 403), f"{method} {path} must allow an employee"
        else:
            assert emp not in (401, 403), f"{method} {path} should allow any signed-in user"
            assert mgr not in (401, 403), f"{method} {path} must allow the manager"


def test_employee_cannot_use_the_copilot_and_nothing_is_written(client, db, logged_in):
    employee, _ = _employee_client(db, "Copilot Intruder")
    runs, messages = db.query(Run).count(), db.query(Message).count()
    r = employee.post("/api/chat", json={"message": "who has not submitted?"})
    assert r.status_code == 403
    assert db.query(Run).count() == runs and db.query(Message).count() == messages
    assert employee.get("/api/conversations").status_code == 403
    assert employee.get("/api/stats").status_code == 403


def test_another_account_cannot_read_a_conversation(client, db, logged_in, fake):
    from app.agent import ModelEvent
    from app.costs import Usage
    from tests.conftest import read_sse

    fake.turns.append([ModelEvent(type="stop", stop_reason="end_turn", usage=Usage(1, 1), content=[{"type": "text", "text": "ok"}])])
    events = read_sse(client.post("/api/chat", json={"message": "private manager question"}))
    conv_id = events[0]["conversation_id"]
    assert client.get(f"/api/conversations/{conv_id}/messages").status_code == 200

    with SessionLocal() as s:  # a second manager account (created directly; managers normally come from the environment)
        other = User(name="Second Manager", access_role="manager", code_hash=hash_secret("another-manager-password"))
        s.add(other)
        s.commit()
    second = TestClient(app, headers=H)
    assert second.post("/api/login", json={"name": "Second Manager", "code": "another-manager-password"}).status_code == 200
    assert second.get(f"/api/conversations/{conv_id}/messages").status_code == 404  # looks nonexistent, not forbidden
    assert conv_id not in [c["id"] for c in second.get("/api/conversations").json()]
    assert second.post("/api/chat", json={"message": "continue it", "conversation_id": conv_id}).status_code == 404
    employee, _ = _employee_client(db, "Curious Employee")
    assert employee.get(f"/api/conversations/{conv_id}/messages").status_code == 403


def test_owned_or_404_helper():
    class Row:
        def __init__(self, user_id):
            self.user_id = user_id

    me = User(id=5, name="x")
    assert auth.owned_or_404(Row(5), me).user_id == 5
    for other in (Row(6), None):
        with pytest.raises(Exception) as info:
            auth.owned_or_404(other, me)
        assert info.value.status_code == 404


def test_employee_records_are_isolated_with_the_shared_pattern(db):
    """The pattern every future employee-owned resource must use: require_employee + owned_or_404 (id from the session)."""
    mini = FastAPI()

    @mini.get("/mine/{conv_id}")
    def mine(conv_id: int, user: User = Depends(auth.require_employee), s: Session = Depends(get_db)):
        return {"id": auth.owned_or_404(s.get(Conversation, conv_id), user).id}

    a, _ = create_employee(db, "Isolation A")
    b, _ = create_employee(db, "Isolation B")
    conv_a, conv_b = Conversation(user_id=a.id, title="a"), Conversation(user_id=b.id, title="b")
    db.add_all([conv_a, conv_b])
    db.commit()

    def as_user(u):
        c = TestClient(mini)
        c.cookies.set("shift_session", auth.make_token(u.id, u.token_version))
        return c

    assert as_user(a).get(f"/mine/{conv_a.id}").status_code == 200
    assert as_user(a).get(f"/mine/{conv_b.id}").status_code == 404  # another employee's record
    assert as_user(b).get(f"/mine/{conv_a.id}").status_code == 404
    assert TestClient(mini).get(f"/mine/{conv_a.id}").status_code == 401
    manager_token = None
    with SessionLocal() as s:
        boss = s.query(User).filter_by(name="boss").one()
        manager_token = auth.make_token(boss.id, boss.token_version)
    mc = TestClient(mini)
    mc.cookies.set("shift_session", manager_token)
    assert mc.get(f"/mine/{conv_a.id}").status_code == 403  # employee routes are not for the manager either


def test_forbidden_is_logged_without_private_data(client, db, logged_in, log_lines):
    employee, user = _employee_client(db, "Logged Intruder")
    employee.get("/api/stats")
    line = log_lines.events("forbidden")[0]
    assert line["user_id"] == user.id and line["required"] == "manager" and line["actual"] == "employee"
    assert "Logged Intruder" not in log_lines.raw()

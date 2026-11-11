"""The operator tool (app/users.py): codes are shown once and stored nowhere; every change is audited atomically."""
import re

import pytest

from app import users as users_module
from app.audit import AuditError
from app.db import AuditLog, SessionLocal, User
from app.users import UserError, create_employee, list_users, main, rotate_code

CODE_RE = re.compile(r"\b[A-HJ-NP-Z2-9]{5}-[A-HJ-NP-Z2-9]{5}\b")


def test_create_prints_the_code_once_and_stores_only_a_hash(capsys, log_lines):
    assert main(["create", "Cli Person"]) == 0
    out = capsys.readouterr().out
    code = CODE_RE.search(out).group(0)
    with SessionLocal() as s:
        user = s.query(User).filter_by(name="Cli Person").one()
        assert user.access_role == "employee" and user.code_hash.startswith("scrypt$")
        assert code not in user.code_hash and code.replace("-", "") not in user.code_hash
        rows = s.query(AuditLog).filter_by(entity="user", entity_id=str(user.id)).all()
        assert [r.action for r in rows] == ["user.created"]
        assert code not in str(rows[0].after_json) and "scrypt" not in str(rows[0].after_json)
        assert rows[0].after_json == {"name": "Cli Person", "access_role": "employee"}
    assert code not in log_lines.raw() and code.replace("-", "") not in log_lines.raw()
    assert log_lines.events("user_created")[0]["user_id"] == user.id


def test_list_shows_names_and_roles_but_never_codes_or_hashes(capsys):
    main(["create", "Listed Person"])
    capsys.readouterr()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Listed Person" in out and "employee" in out and "boss" in out
    assert "scrypt" not in out and not CODE_RE.search(out)


def test_rotate_issues_a_new_code_and_audits_without_it(db, capsys):
    user, old = create_employee(db, "Rotated Person")
    before = user.token_version
    assert main(["rotate", "Rotated Person"]) == 0
    new = CODE_RE.search(capsys.readouterr().out).group(0)
    db.refresh(user)
    assert new != old and user.token_version == before + 1
    rows = db.query(AuditLog).filter_by(entity="user", entity_id=str(user.id)).order_by(AuditLog.id).all()
    assert [r.action for r in rows] == ["user.created", "user.code_rotated"]
    assert new not in str([r.after_json for r in rows])


def test_refusals(db, capsys):
    create_employee(db, "Taken Name")
    assert main(["create", "taken name"]) == 1  # case-insensitive duplicate
    assert main(["create", "<bad>"]) == 1
    assert main(["rotate", "No Such Person"]) == 1
    assert main(["rotate", "boss"]) == 1  # the manager password lives in the environment
    err = capsys.readouterr().err
    assert "already exists" in err and "2-40" in err and "No such account" in err and "MANAGER_PASSWORD" in err
    assert db.query(User).filter(User.name.in_(["<bad>", "taken name"])).count() == 0


def test_failing_audit_aborts_account_creation(db, monkeypatch):
    def broken(*a, **k):
        raise AuditError("audit down")

    monkeypatch.setattr(users_module, "record", broken)
    with pytest.raises(AuditError):
        create_employee(db, "Never Created")
    assert db.query(User).filter_by(name="Never Created").count() == 0  # no account without its audit record


def test_users_without_a_code_cannot_log_in(client, db):
    with SessionLocal() as s:
        s.add(User(name="Legacy Row"))  # like a user row from before migration 0002
        s.commit()
    r = client.post("/api/login", json={"name": "Legacy Row", "code": "ZZZZZ-ZZZZZ"})
    assert r.status_code == 401
    assert [u for u in list_users(db) if u["name"] == "Legacy Row"][0]["has_code"] is False
    with pytest.raises(UserError):
        create_employee(db, "legacy row")

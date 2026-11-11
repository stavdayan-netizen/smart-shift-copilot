"""Session tokens, access codes and the login flow (app/auth.py, app/passwords.py)."""
import base64
import time

from app import auth, passwords
from app.db import SessionLocal, User
from app.users import create_employee

SECRET_HEADER = {"X-Requested-With": "shift-copilot"}


def _employee(db, name):
    user, code = create_employee(db, name)
    return user, code


def test_session_token_round_trips_for_every_second(monkeypatch):
    # The expiry is a whole second, so 1,000 consecutive seconds give 1,000 different
    # signatures; about one raw HMAC digest in nine contains the byte '|' (ticket 25).
    start = 1_800_000_000
    for offset in range(1000):
        monkeypatch.setattr(auth.time, "time", lambda: start + offset)
        assert auth.read_token(auth.make_token(1, 0)) == (1, 0), f"rejected at second {offset}"


def test_tampered_or_expired_token_is_rejected(monkeypatch):
    payload, sig = base64.urlsafe_b64decode(auth.make_token(1, 0)).rsplit(b"|", 1)

    def encode(p: bytes, s: bytes) -> str:
        return base64.urlsafe_b64encode(p + b"|" + s).decode()

    other_user = payload.replace(b"1|", b"2|", 1)  # claims user 2 under user 1's signature
    flipped = sig[:-1] + (b"0" if sig[-1:] != b"0" else b"1")
    assert auth.read_token(encode(payload, sig)) == (1, 0)
    assert auth.read_token(encode(other_user, sig)) is None
    assert auth.read_token(encode(payload, flipped)) is None
    assert auth.read_token("not-a-token") is None and auth.read_token(None) is None
    token = auth.make_token(1, 0)
    monkeypatch.setattr(auth.time, "time", lambda: time.time() + 25 * 3600)  # session lifetime is 24 hours
    assert auth.read_token(token) is None


def test_codes_are_random_readable_and_normalised():
    codes = {passwords.generate_code() for _ in range(200)}
    assert len(codes) == 200
    for c in codes:
        assert len(c) == 11 and c[5] == "-" and set(c.replace("-", "")) <= set(passwords.ALPHABET)
    assert passwords.normalize_code(" abcde-fgh23 ") == "ABCDEFGH23"


def test_hash_is_salted_verifiable_and_not_the_secret():
    a, b = passwords.hash_secret("S3CRETCODE"), passwords.hash_secret("S3CRETCODE")
    assert a != b and a.startswith("scrypt$") and "S3CRETCODE" not in a
    assert passwords.verify_secret("S3CRETCODE", a) and not passwords.verify_secret("s3cretcode", a)
    assert not passwords.verify_secret("anything", None)  # no hash: still does the work, never succeeds
    assert not passwords.verify_secret("anything", "garbage")
    assert not passwords.verify_secret(passwords.normalize_code("x"), passwords.DUMMY_HASH)


def test_employee_logs_in_with_name_and_code_in_any_format(client, db):
    user, code = _employee(db, "Login Employee")
    assert user.code_hash and code not in user.code_hash
    r = client.post("/api/login", json={"name": "Login Employee", "code": code.lower().replace("-", " ")}, headers=SECRET_HEADER)
    assert r.status_code == 200 and r.json() == {"id": user.id, "name": "Login Employee", "role": "employee"}
    cookie = r.headers["set-cookie"].lower()
    assert "shift_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "max-age=86400" in cookie
    me = client.get("/api/me")
    assert me.status_code == 200 and me.json()["role"] == "employee"


def test_manager_logs_in_with_the_environment_password(client):
    r = client.post("/api/login", json={"name": "boss", "code": "test-manager-password"}, headers=SECRET_HEADER)
    assert r.status_code == 200 and r.json()["role"] == "manager"
    assert client.post("/api/login", json={"name": "boss", "code": "TEST-MANAGER-PASSWORD"}, headers=SECRET_HEADER).status_code == 401


def test_wrong_code_and_unknown_name_look_identical(client, db):
    _employee(db, "Identical Failure")
    wrong = client.post("/api/login", json={"name": "Identical Failure", "code": "ZZZZZ-ZZZZZ"}, headers=SECRET_HEADER)
    unknown = client.post("/api/login", json={"name": "Nobody Here", "code": "ZZZZZ-ZZZZZ"}, headers=SECRET_HEADER)
    badname = client.post("/api/login", json={"name": "<script>", "code": "ZZZZZ-ZZZZZ"}, headers=SECRET_HEADER)
    assert wrong.status_code == unknown.status_code == badname.status_code == 401
    assert wrong.json() == unknown.json() == badname.json() == {"detail": auth.GENERIC_FAILURE}
    assert wrong.headers.get("set-cookie") is None


def test_unknown_name_still_does_the_hashing_work(client, monkeypatch):
    calls = []
    real = passwords.verify_secret
    monkeypatch.setattr(passwords, "verify_secret", lambda secret, stored: calls.append(stored) or real(secret, stored))
    client.post("/api/login", json={"name": "Never Created", "code": "ZZZZZ-ZZZZZ"}, headers=SECRET_HEADER)
    assert calls == [None]  # verified against the dummy hash, same cost as a real account


def test_no_self_registration(client, db):
    r = client.post("/api/login", json={"name": "Brand New Person", "code": "anything"}, headers=SECRET_HEADER)
    assert r.status_code == 401
    assert db.query(User).filter_by(name="Brand New Person").count() == 0


def test_rotating_a_code_signs_the_user_out_everywhere(client, db):
    from app.users import rotate_code

    user, code = _employee(db, "Rotating Employee")
    assert client.post("/api/login", json={"name": user.name, "code": code}, headers=SECRET_HEADER).status_code == 200
    assert client.get("/api/me").status_code == 200
    _, new_code = rotate_code(db, user.name)
    assert client.get("/api/me").status_code == 401  # the old session is dead
    assert client.post("/api/login", json={"name": user.name, "code": code}, headers=SECRET_HEADER).status_code == 401
    assert client.post("/api/login", json={"name": user.name, "code": new_code}, headers=SECRET_HEADER).status_code == 200


def test_role_comes_from_the_database_not_the_cookie(client, db):
    user, code = _employee(db, "Role Check")
    client.post("/api/login", json={"name": user.name, "code": code}, headers=SECRET_HEADER)
    assert client.get("/api/stats").status_code == 403
    # Promote in the database: the same cookie now carries manager rights, because the role is read from the row.
    with SessionLocal() as s:
        s.get(User, user.id).access_role = "manager"
        s.commit()
    try:
        assert client.get("/api/stats").status_code == 200
    finally:
        with SessionLocal() as s:
            s.get(User, user.id).access_role = "employee"
            s.commit()


def test_user_deleted_or_unknown_in_cookie_is_signed_out(client):
    client.cookies.set("shift_session", auth.make_token(99999, 0))
    assert client.get("/api/me").status_code == 401


def test_logout_clears_the_cookie(client, logged_in):
    r = client.post("/api/logout", headers=SECRET_HEADER)
    assert r.status_code == 204 and "shift_session=" in r.headers["set-cookie"]


def test_secure_cookie_in_production(client, monkeypatch):
    from app.config import settings
    import dataclasses

    import app.main as main

    monkeypatch.setattr(main, "settings", dataclasses.replace(settings, environment="production"))
    r = client.post("/api/login", json={"name": "boss", "code": "test-manager-password"}, headers=SECRET_HEADER)
    assert "secure" in r.headers["set-cookie"].lower()


def test_manager_bootstrap_creates_follows_password_changes_and_audits(db, monkeypatch):
    import dataclasses

    from app import auth as auth_module
    from app.config import settings
    from app.db import AuditLog

    name = "bootstrap-boss"
    s1 = dataclasses.replace(settings, manager_name=name, manager_password="first-manager-password")
    monkeypatch.setattr(auth_module, "settings", s1)
    assert auth_module.ensure_manager(db) == "created"
    assert auth_module.ensure_manager(db) == "unchanged"
    user = db.query(User).filter_by(name=name).one()
    version = user.token_version
    monkeypatch.setattr(auth_module, "settings", dataclasses.replace(s1, manager_password="second-manager-password"))
    assert auth_module.ensure_manager(db) == "updated"
    db.refresh(user)
    assert user.token_version == version + 1  # old manager sessions stop working
    rows = db.query(AuditLog).filter(AuditLog.entity == "user", AuditLog.entity_id == str(user.id)).all()
    assert {r.action for r in rows} == {"user.manager_created", "user.manager_password_changed"}
    assert "password" not in str([r.after_json for r in rows]).lower().replace("manager_password_changed", "")
    monkeypatch.setattr(auth_module, "settings", dataclasses.replace(s1, manager_password=None))
    assert auth_module.ensure_manager(db) == "disabled"


def test_manager_name_must_not_collide_with_an_employee(db, monkeypatch):
    import dataclasses

    import pytest

    from app import auth as auth_module
    from app.config import settings

    _employee(db, "Collision Name")
    monkeypatch.setattr(auth_module, "settings", dataclasses.replace(settings, manager_name="Collision Name"))
    with pytest.raises(RuntimeError, match="MANAGER_NAME"):
        auth_module.ensure_manager(db)

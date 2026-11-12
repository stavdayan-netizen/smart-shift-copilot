"""CSRF policy (app/security.py): custom header required, Origin must match when present, no CORS."""
import dataclasses

from fastapi.testclient import TestClient

from app import security
from app.config import settings
from app.main import app

H = {"X-Requested-With": "shift-copilot"}
LOGIN = {"name": "boss", "code": "test-manager-password"}


def _browserless():
    """A client with no default headers: what a cross-site form or script could actually send."""
    return TestClient(app)


def test_state_changing_request_without_the_custom_header_is_blocked(log_lines):
    c = _browserless()
    for headers in ({}, {"X-Requested-With": "XMLHttpRequest"}, {"Content-Type": "text/plain"}):
        r = c.post("/api/login", json=LOGIN, headers=headers)
        assert r.status_code == 403 and r.json() == {"detail": "הבקשה נחסמה."}
        assert "set-cookie" not in r.headers
    assert {e["reason"] for e in log_lines.events("csrf_blocked")} == {"missing_header"}
    assert any(e["status"] == 403 for e in log_lines.events("request"))  # blocked requests are still logged with an id


def test_cross_site_origin_is_blocked_even_with_the_header(client, logged_in):
    for origin in ("https://evil.example", "null", "http://testserver.evil.example"):
        r = client.post("/api/chat", json={"message": "hi"}, headers={"Origin": origin})
        assert r.status_code == 403, origin
    r = client.post("/api/chat", json={"message": "hi"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_and_headerless_non_browser_requests_with_the_header_pass(client, logged_in):
    assert client.post("/api/chat", json={"message": "hi"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/chat", json={"message": "hi"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200  # no Origin at all, header present


def test_safe_methods_and_the_cron_endpoint_are_not_subject_to_the_header():
    c = _browserless()
    assert c.get("/health").status_code == 200
    assert c.get("/").status_code == 200
    assert c.post("/internal/digest", headers={"X-Cron-Secret": "cron-test"}).status_code == 200  # no cookie, own secret


def test_csrf_forged_login_cannot_set_a_session():
    r = _browserless().post("/api/login", data=LOGIN)  # what a cross-site HTML form would send
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_allowed_origins_setting_opens_exactly_those_origins(client, logged_in, monkeypatch):
    monkeypatch.setattr(security, "settings", dataclasses.replace(settings, allowed_origins="https://shift.example, https://other.example"))
    assert client.post("/api/chat", json={"message": "hi"}, headers={"Origin": "https://shift.example"}).status_code == 200
    assert client.post("/api/chat", json={"message": "hi"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_api_responses_are_not_cached(client, logged_in):
    assert client.get("/api/me").headers["cache-control"] == "no-store"
    assert client.get("/api/conversations").headers["cache-control"] == "no-store"
    assert "no-store" in _browserless().post("/api/login", json=LOGIN).headers["cache-control"]


def test_no_cors_headers_are_ever_sent(client, logged_in):
    r = client.get("/api/me", headers={"Origin": "https://evil.example"})
    assert not any(h.lower().startswith("access-control-") for h in r.headers)
    pre = _browserless().options("/api/chat", headers={"Origin": "https://evil.example",
                                                       "Access-Control-Request-Method": "POST",
                                                       "Access-Control-Request-Headers": "x-requested-with"})
    assert not any(h.lower().startswith("access-control-") for h in pre.headers)  # a preflight can never succeed

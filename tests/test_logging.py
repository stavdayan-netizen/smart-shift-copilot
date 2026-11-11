"""Structured logging: JSON shape, request ids, redaction. Nothing sensitive may reach the logs."""
import datetime
import json
import logging

from app.logging_setup import JsonFormatter, accept_request_id, log_event, log_exception, redact
from app.migrations import schema_status
from tests.conftest import read_sse

SECRET_PASSWORD = "hunter2-very-secret"
PRIVATE_TEXT = "please give me Sunday off, my mother-in-law Rivka is visiting from Haifa"


def test_log_line_is_json_with_required_fields(log_lines):
    log_event("something_happened", user_id=7, duration_ms=12)
    line = log_lines.events("something_happened")[0]
    assert {"ts", "level", "event"} <= set(line)
    assert line["level"] == "info" and line["user_id"] == 7 and line["duration_ms"] == 12
    assert line["ts"].endswith("Z")


def test_redact_removes_credentials_and_reduces_private_text():
    out = redact({"password": "x", "Authorization": "Bearer abcdefghijkl", "api_key": "sk-ant-abcdefgh1234",
                  "message": PRIVATE_TEXT, "free_text": PRIVATE_TEXT, "user_id": 3,
                  "nested": {"session_token": "abc", "items": [{"cookie": "shift_session=zzz"}]},
                  "other": "key sk-ant-abcdefghijk leaked", "where": "cookie shift_session=abcdef123456 here"})
    dumped = json.dumps(out)
    for needle in ("Bearer abcdefghijkl", "sk-ant-abcdefg", "mother-in-law", "shift_session=zzz", "abcdef123456"):
        assert needle not in dumped
    assert out["password"] == "[redacted]" and out["user_id"] == 3
    assert out["message"].startswith("[private len=")
    assert "[redacted-api-key]" in out["other"]


def test_token_counts_are_not_mistaken_for_secrets():
    out = redact({"input_tokens": 120, "output_tokens": 18, "cache_read_tokens": 0})
    assert out == {"input_tokens": 120, "output_tokens": 18, "cache_read_tokens": 0}


def test_audit_style_redaction_keeps_business_text_but_not_credentials():
    out = redact({"free_text": "day off please", "password": "p"}, private=False)
    assert out == {"free_text": "day off please", "password": "[redacted]"}


def test_exception_logs_type_and_stack_but_never_the_message(log_lines):
    try:
        raise ValueError(f"INSERT ... VALUES ('{PRIVATE_TEXT}')")
    except ValueError as exc:
        log_exception("boom", exc, where="test")
    line = log_lines.events("boom")[0]
    assert line["error_type"] == "ValueError" and line["stack"] and line["where"] == "test"
    assert "mother-in-law" not in log_lines.raw() and "INSERT" not in log_lines.raw()


def test_plain_logging_calls_are_json_and_scrubbed(log_lines):
    logging.getLogger("some.library").warning("calling with api_key=%s", "sk-ant-abcdefghijk1234")
    line = [e for e in log_lines() if e.get("logger") == "some.library"][0]
    assert line["event"] == "log" and "sk-ant" not in json.dumps(line)


def test_request_id_is_returned_logged_and_reused(client, log_lines):
    r = client.get("/health")
    rid = r.headers["x-request-id"]
    assert len(rid) >= 8
    req = [e for e in log_lines.events("request") if e["request_id"] == rid][0]
    assert req["route"] == "/health" and req["status"] == 200 and "duration_ms" in req and req["method"] == "GET"
    r2 = client.get("/health", headers={"X-Request-ID": "client-supplied-id-123"})
    assert r2.headers["x-request-id"] == "client-supplied-id-123"


def test_unsafe_request_id_is_replaced():
    assert accept_request_id("short") != "short"
    assert accept_request_id('bad id with spaces and "quotes"').isalnum()
    assert accept_request_id(None)
    assert accept_request_id("a" * 65) != "a" * 65


def test_events_inside_a_request_share_its_request_id(client, logged_in, fake, log_lines):
    events = read_sse(client.post("/api/chat", json={"message": "hello"}))
    assert events[-1]["type"] == "done"
    rid = next(e["request_id"] for e in log_lines.events("request") if e["route"] == "/api/chat")
    for name in ("copilot_request", "copilot_run"):
        assert log_lines.events(name)[-1]["request_id"] == rid
    run = log_lines.events("copilot_run")[-1]
    assert run["status"] == "ok" and run["input_tokens"] == 10 and "effort" in run and "cost_usd" in run


def test_secrets_and_private_text_never_reach_the_logs(client, fake, log_lines):
    client.cookies.clear()
    bad = client.post("/api/login", json={"name": "boss", "code": SECRET_PASSWORD})
    assert bad.status_code == 401
    good = client.post("/api/login", json={"name": "boss", "code": "test-manager-password"})
    assert good.status_code == 200
    token = client.cookies.get("shift_session")
    assert token
    client.post("/api/chat", json={"message": PRIVATE_TEXT})
    client.get("/api/conversations")
    raw = log_lines.raw()
    assert SECRET_PASSWORD not in raw and "test-manager-password" not in raw
    assert token not in raw and "test-secret-0123456789abcdef" not in raw
    assert "mother-in-law" not in raw and "Rivka" not in raw and PRIVATE_TEXT not in raw
    failed = log_lines.events("auth_failed")[0]
    assert failed["reason"] == "bad_credentials" and failed["level"] == "warning"
    assert log_lines.events("copilot_request")[-1]["message_len"] == len(PRIVATE_TEXT)


def test_app_start_event_and_schema_check(client, log_lines):
    from fastapi.testclient import TestClient

    from app.db import engine
    from app.main import app

    with TestClient(app):
        pass
    start = log_lines.events("app_start")[0]
    assert start["schema"] == "current" and start["provider"] == "fake" and "model" in start
    assert log_lines.events("app_stop")
    assert schema_status(engine)["state"] == "current"


def test_health_reports_pending_migrations(client, monkeypatch, log_lines):
    import app.main as main

    monkeypatch.setattr(main, "schema_status", lambda e: {"state": "pending", "current": None, "head": "0001"})
    r = client.get("/health")
    assert r.status_code == 503
    assert any("migrations pending" in p for p in r.json()["detail"]["problems"])
    assert log_lines.events("health_failed")


def test_unknown_tool_logs_without_input(client, db, log_lines):
    from app.tools import registry

    registry.execute("nope", {"secret_thing": SECRET_PASSWORD}, db)
    line = log_lines.events("tool_executed")[0]
    assert line["tool"] == "nope" and line["status"] == "unknown_tool"
    assert SECRET_PASSWORD not in log_lines.raw()


def test_formatter_handles_non_serialisable_values():
    rec = logging.LogRecord("app", logging.INFO, __file__, 1, "x", None, None)
    rec.event, rec.fields = "odd", {"obj": object(), "when": datetime.datetime(2026, 1, 1)}
    assert json.loads(JsonFormatter().format(rec))["event"] == "odd"

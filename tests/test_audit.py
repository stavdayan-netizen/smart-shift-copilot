"""Audit log: atomic with the change it records, append-only, separate from operational logs."""
import datetime
import uuid

import pytest

from app import audit
from app.audit import AuditError, AuditMissing, audited, record
from app.db import AuditLog, Conversation, SessionLocal, User
from app.logging_setup import request_id_var


@pytest.fixture
def conv(db):
    user = User(name=f"audit-{uuid.uuid4().hex[:8]}")
    db.add(user)
    db.commit()
    c = Conversation(user_id=user.id, title="before")
    db.add(c)
    db.commit()
    return c


def _title(conv_id):
    with SessionLocal() as s:
        return s.get(Conversation, conv_id).title


def _audit_rows(entity_id):
    with SessionLocal() as s:
        return s.query(AuditLog).filter_by(entity="conversation", entity_id=str(entity_id)).order_by(AuditLog.id).all()


def test_mutation_and_audit_commit_together(db, conv):
    with audited(db):
        conv.title = "after"
        record(db, actor_id=conv.user_id, action="conversation.rename", entity="conversation",
               entity_id=conv.id, before={"title": "before"}, after={"title": "after"})
    assert _title(conv.id) == "after"
    rows = _audit_rows(conv.id)
    assert len(rows) == 1
    assert rows[0].action == "conversation.rename" and rows[0].actor_id == conv.user_id
    assert rows[0].before_json == {"title": "before"} and rows[0].after_json == {"title": "after"}


def test_failing_audit_record_rolls_back_the_mutation(db, conv):
    with pytest.raises(AuditError):
        with audited(db):
            conv.title = "should not stick"
            record(db, actor_id=conv.user_id, action="", entity="conversation", entity_id=conv.id)
    assert _title(conv.id) == "before"
    assert _audit_rows(conv.id) == []


def test_database_failure_while_writing_audit_rolls_back(db, conv, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(audit, "AuditLog", broken)
    with pytest.raises(AuditError):
        with audited(db):
            conv.title = "should not stick"
            record(db, actor_id=conv.user_id, action="conversation.rename", entity="conversation", entity_id=conv.id)
    assert _title(conv.id) == "before"


def test_block_without_an_audit_record_is_refused_and_rolled_back(db, conv):
    with pytest.raises(AuditMissing):
        with audited(db):
            conv.title = "silent change"
    assert _title(conv.id) == "before"


def test_exception_after_audit_rolls_back_both(db, conv):
    with pytest.raises(ValueError):
        with audited(db):
            conv.title = "half done"
            record(db, actor_id=conv.user_id, action="conversation.rename", entity="conversation", entity_id=conv.id)
            raise ValueError("later step failed")
    assert _title(conv.id) == "before"
    assert _audit_rows(conv.id) == []


def test_credentials_are_redacted_but_business_text_is_kept(db, conv):
    with audited(db):
        record(db, actor_id=conv.user_id, action="request.decided", entity="conversation", entity_id=conv.id,
               after={"note": "approved, covers Sunday", "password": "p4ss", "when": datetime.datetime(2026, 1, 1)})
    row = _audit_rows(conv.id)[0]
    assert row.after_json["note"] == "approved, covers Sunday"
    assert row.after_json["password"] == "[redacted]"
    assert row.after_json["when"].startswith("2026-01-01")


def test_audit_rows_are_append_only(db, conv):
    with audited(db):
        row = record(db, actor_id=None, action="x.y", entity="conversation", entity_id=conv.id)
    row_id = row.id
    with SessionLocal() as s:
        r = s.get(AuditLog, row_id)
        r.action = "tampered"
        with pytest.raises(AuditError):
            s.flush()
        s.rollback()
        r = s.get(AuditLog, row_id)
        s.delete(r)
        with pytest.raises(AuditError):
            s.flush()
        s.rollback()
    assert _audit_rows(conv.id)[0].action == "x.y"


def test_audit_row_remembers_the_request_id(db, conv):
    token = request_id_var.set("req-abc-123456")
    try:
        with audited(db):
            record(db, actor_id=None, action="x.y", entity="conversation", entity_id=conv.id)
    finally:
        request_id_var.reset(token)
    assert _audit_rows(conv.id)[0].request_id == "req-abc-123456"


def test_operational_log_gets_the_audit_event_but_never_the_payload(db, conv, log_lines):
    secret_business_text = "swap requested because of Rivka's surgery"
    with audited(db):
        record(db, actor_id=conv.user_id, action="request.decided", entity="conversation", entity_id=conv.id,
               before={"note": secret_business_text}, after={"note": secret_business_text + " (approved)"})
    line = log_lines.events("audit_recorded")[0]
    assert line["action"] == "request.decided" and line["entity"] == "conversation" and line["audit_id"]
    assert "before_json" not in line and "after_json" not in line
    assert "Rivka" not in log_lines.raw() and "surgery" not in log_lines.raw()
    assert "Rivka" in str(_audit_rows(conv.id)[0].before_json)  # the business record keeps it

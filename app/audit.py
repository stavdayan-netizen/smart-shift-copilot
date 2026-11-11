"""The audit log: the durable business record of who changed what.

Not the same as operational logs (app/logging_setup.py):
- audit rows live in the database, are part of the same transaction as the change
  they describe, and are never rewritten or deleted;
- operational logs are best-effort stdout lines for diagnosing the system. They get
  only the audit row's id, action and entity, NEVER its before/after payloads.

Use it for every critical business mutation (a submission after the deadline, a
change-request decision, a draft, a publish, a confirmed schedule change):

    with audited(db) as tx:
        conv.title = "new title"                  # the mutation
        audit.record(db, actor_id=user.id, action="conversation.rename",
                     entity="conversation", entity_id=conv.id,
                     before={"title": old}, after={"title": conv.title})
    # committed together here; if record() fails, or no audit row was written, both roll back

`record()` never commits. `audited()` commits once, after checking that at least
one audit row was written inside the block, so a critical mutation cannot succeed
silently without its audit record.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session

from .db import AuditLog
from .logging_setup import get_request_id, log_event, redact


class AuditError(RuntimeError):
    """The audit record could not be written; the surrounding mutation must not be committed."""


class AuditMissing(AuditError):
    """A block that required an audit record finished without writing one."""


def _payload(value: Any) -> Any:
    """JSON-safe copy of a before/after payload with credentials removed (business text is kept)."""
    if value is None:
        return None
    cleaned = redact(value, private=False)
    try:
        json.dumps(cleaned)
    except (TypeError, ValueError) as exc:  # pragma: no cover - redact() already stringifies unknown types
        raise AuditError(f"audit payload is not JSON-serialisable: {type(exc).__name__}") from exc
    return cleaned


def record(db: Session, *, actor_id: int | None, action: str, entity: str, entity_id: Any = None,
           before: Any = None, after: Any = None) -> AuditLog:
    """Add one audit row to the caller's transaction and flush it. Does not commit."""
    if not action or not entity:
        raise AuditError("audit records need an action and an entity")
    try:
        row = AuditLog(actor_id=actor_id, action=action[:60], entity=entity[:60],
                       entity_id=None if entity_id is None else str(entity_id)[:40],
                       request_id=get_request_id(), before_json=_payload(before), after_json=_payload(after))
        db.add(row)
        db.flush()  # surfaces a failing audit write now, inside the caller's transaction
    except AuditError:
        raise
    except Exception as exc:
        raise AuditError(f"audit record could not be written: {type(exc).__name__}") from exc
    db.info["audit_rows"] = db.info.get("audit_rows", 0) + 1
    log_event("audit_recorded", audit_id=row.id, action=row.action, entity=row.entity, entity_id=row.entity_id)
    return row


@contextmanager
def audited(db: Session) -> Iterator[Session]:
    """Commit the block's changes and its audit record atomically, or neither."""
    db.info["audit_rows"] = 0
    try:
        yield db
        if db.info.get("audit_rows", 0) < 1:
            raise AuditMissing("critical mutation finished without an audit record")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.info["audit_rows"] = 0


# Append-only: the ORM refuses to change or delete an audit row.
@event.listens_for(AuditLog, "before_update")
def _no_update(mapper, connection, target):  # pragma: no cover - exercised by tests through flush
    raise AuditError("audit rows are append-only")


@event.listens_for(AuditLog, "before_delete")
def _no_delete(mapper, connection, target):  # pragma: no cover
    raise AuditError("audit rows are append-only")

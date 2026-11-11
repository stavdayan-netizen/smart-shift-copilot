"""Structured operational logging: one JSON object per line on stdout.

Operational logs are for diagnosing the running system. They are best effort,
rotate on Railway, and are NOT the business record: anything the business must
be able to prove (who changed what) goes to the `audit_log` table (app/audit.py).

Rules enforced here (practice.md section 6):
- every line has `ts`, `level`, `event`, and `request_id` when inside a request;
- values pass through `redact()` before they are written: credentials are replaced,
  private text (messages, prompts, free-text requests) is reduced to its length;
- exceptions are logged as `error_type` plus a short stack of `file:line in function`.
  The exception *message* is never logged, because database errors embed SQL parameters.

Use `log_event("something_happened", key=value)`; never format personal data into
the event name or log raw request bodies.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_HANDLER_MARK = "_shift_json_handler"
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Credentials: replaced everywhere (logs and audit payloads).
SECRET_KEYS = {
    "password", "passwd", "pwd", "secret", "token", "access_token", "session", "session_token", "cookie",
    "set-cookie", "authorization", "api_key", "apikey", "x-api-key", "x-cron-secret", "code", "access_code",
    "code_hash", "pin", "private_key",
}
_SECRET_SUFFIXES = ("_password", "_secret", "_token", "_api_key", "_cookie", "_code")
# Private text: reduced to its length in logs (the audit log may keep business text).
PRIVATE_KEYS = {
    "message", "messages", "content", "prompt", "system_prompt", "free_text", "text", "note", "notes",
    "explanation", "request_text", "body", "input",
}

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[redacted-api-key]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"(?i)\b(bc_session|session|token|password|secret|api[_-]?key)=([^\s;&,]+)"), r"\1=[redacted]"),
]
_MAX_STR = 500


def _norm(key: Any) -> str:
    return str(key).strip().lower()


def is_secret_key(key: Any) -> bool:
    k = _norm(key)
    return k in SECRET_KEYS or k.endswith(_SECRET_SUFFIXES)


def is_private_key(key: Any) -> bool:
    return _norm(key) in PRIVATE_KEYS


def scrub_string(s: str) -> str:
    for pattern, repl in _PATTERNS:
        s = pattern.sub(repl, s)
    return s if len(s) <= _MAX_STR else s[:_MAX_STR] + "...[truncated]"


def redact(value: Any, *, private: bool = True, _key: Any = None) -> Any:
    """Return a JSON-safe copy of `value` with credentials removed.

    private=True (logs): private text values are replaced by their length.
    private=False (audit payloads): only credentials are removed.
    """
    if _key is not None:
        if is_secret_key(_key):
            return "[redacted]"
        if private and is_private_key(_key):
            n = len(value) if isinstance(value, (str, bytes, list, tuple, dict)) else 0
            return f"[private len={n}]"
    if isinstance(value, dict):
        return {str(k): redact(v, private=private, _key=k) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v, private=private) for v in value]
    if isinstance(value, str):
        return scrub_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return scrub_string(str(value))


def error_fields(exc: BaseException) -> dict[str, Any]:
    """`error_type` and a message-free stack. Never includes str(exc)."""
    frames = traceback.extract_tb(exc.__traceback__)[-8:]
    return {"error_type": type(exc).__name__,
            "stack": [f"{f.filename.replace(chr(92), '/').split('/app/')[-1]}:{f.lineno} in {f.name}" for f in frames]}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None)
        fields = getattr(record, "fields", None) or {}
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": event or "log",
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        if event is None:
            payload["logger"] = record.name
            payload["message"] = scrub_string(record.getMessage())
        payload.update(redact(fields))
        if record.exc_info and record.exc_info[1] is not None:
            payload.update(error_fields(record.exc_info[1]))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger and route uvicorn through it. Idempotent."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_MARK, False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(level.upper() if level.upper() in logging._nameToLevel else "INFO")
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")  # replaced by our `request` event
    access.handlers = []
    access.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)  # the CLI keeps its own INFO output


_log = logging.getLogger("app")


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    _log.log(logging._nameToLevel.get(level.upper(), logging.INFO), event, extra={"event": event, "fields": fields})


def log_exception(event: str, exc: BaseException, level: str = "error", **fields: Any) -> None:
    """Log an exception as `error_type` + stack, without its message."""
    log_event(event, level, **fields, **error_fields(exc))


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def accept_request_id(candidate: str | None) -> str:
    """Use a caller-supplied id only if it looks like an id; it is a label, never trusted for anything else."""
    return candidate if candidate and _REQUEST_ID_OK.match(candidate) else new_request_id()


def get_request_id() -> str | None:
    return request_id_var.get()


class RequestContextMiddleware:
    """Pure ASGI middleware: request id in, `X-Request-ID` out, one `request` event per request.

    Pure ASGI (not BaseHTTPMiddleware) so streaming chat responses and client
    disconnects behave exactly as before.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        rid = accept_request_id(headers.get("x-request-id"))
        token = request_id_var.set(rid)
        started = datetime.now(timezone.utc)
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # the request id is still set here; handlers further out would not see it
            log_exception("unhandled_error", exc)
            raise
        finally:
            route = scope.get("route")
            log_event("request", method=scope.get("method"),
                      route=getattr(route, "path", None) or ("static" if scope.get("path", "").startswith("/static") else "unmatched"),
                      status=status["code"],
                      duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
            request_id_var.reset(token)

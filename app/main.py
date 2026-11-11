"""Smart Shift Copilot backend: the API, the static UI, the health check, the digest hook.

One service does everything (architecture.md, "Where things run"). The agent
loop itself lives in agent.py; this file is doors, locks and plumbing.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import auth, limits
from .logging_setup import RequestContextMiddleware, configure_logging, log_event, log_exception
from .agent import get_model_client, run_turn
from .config import ROOT, settings
from .db import Conversation, Message, SessionLocal, engine, get_db
from .digest import build_digest, send_digest
from .migrations import schema_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    try:
        app.state.schema = schema_status(engine)
    except Exception as exc:  # the database may be down at boot; /health reports it
        app.state.schema = {"state": "unknown"}
        log_exception("db_error", exc, where="startup_schema_check")
    app.state.model_client = get_model_client()
    # One line in the deploy log so a first deploy can be checked (runbook.md section 1).
    log_event("app_start", env=settings.environment, model=settings.model, provider=settings.model_provider,
              db="sqlite" if settings.is_sqlite else "postgres", schema=app.state.schema.get("state"),
              log_level=settings.log_level)
    if app.state.schema.get("state") == "pending":
        log_event("migrations_pending", "warning", current=app.state.schema.get("current"), head=app.state.schema.get("head"))
    yield
    log_event("app_stop")


configure_logging(settings.log_level)
app = FastAPI(title="Smart Shift Copilot", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(RequestContextMiddleware)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class ChatIn(BaseModel):
    conversation_id: int | None = None
    message: str = Field(default="", max_length=4000)


# ---------------------------------------------------------------------------
# Pages and health
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Railway's health check. 200 only when the database answers and a model is configured."""
    problems = []
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised on a broken deploy, not in tests
        problems.append(f"db: {type(exc).__name__}")
        log_exception("db_error", exc, where="health")
    else:
        try:
            status = schema_status(engine)
            if status["state"] != "current":
                problems.append("schema: migrations pending (run alembic upgrade head)")
        except Exception as exc:  # pragma: no cover
            problems.append(f"schema: {type(exc).__name__}")
            log_exception("db_error", exc, where="health_schema")
    if settings.model_provider == "anthropic" and not settings.anthropic_api_key:
        problems.append("ANTHROPIC_API_KEY missing")
    body = {"status": "ok" if not problems else "degraded", "env": settings.environment, "model": settings.model,
            "provider": settings.model_provider, "db": "sqlite" if settings.is_sqlite else "postgres", "problems": problems,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if problems:
        log_event("health_failed", "warning", problems=problems)
        raise HTTPException(503, body)
    return body


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    if not auth.password_ok(payload.password):
        log_event("auth_failed", "warning", reason="bad_password")
        raise HTTPException(401, "Wrong password.")
    user = auth.get_or_create_user(db, auth.normalise_name(payload.name))
    response.set_cookie(auth.COOKIE_NAME, auth.make_token(user.id, user.name), httponly=True, samesite="lax",
                        secure=settings.is_production, max_age=settings.session_hours * 3600, path="/")
    return {"id": user.id, "name": user.name}


@app.post("/api/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return Response(status_code=204)


@app.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    return {"id": user.id, "name": user.name}


# ---------------------------------------------------------------------------
# Conversations and messages
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                      .order_by(Conversation.updated_at.desc()).limit(100)).all()
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat(timespec="seconds")} for c in rows]


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found.")
    rows = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    return [{"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat(timespec="seconds")} for m in rows]


@app.post("/api/chat")
def chat(payload: ChatIn, request: Request, db: Session = Depends(get_db)):
    """One turn. Checks the three limits, then streams the agent's events as SSE."""
    user = auth.current_user(request, db)
    if not payload.message.strip():
        raise HTTPException(400, "Say something.")
    limits.check_rate_limit(db, user.id)
    limits.check_daily_cap(db)
    log_event("copilot_request", user_id=user.id, conversation_id=payload.conversation_id, message_len=len(payload.message))

    conv = None
    if payload.conversation_id is not None:
        conv = db.get(Conversation, payload.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found.")
    conv_id = conv.id if conv else None
    user_id = user.id
    client = request.app.state.model_client

    def sse():
        # A dedicated session: the request-scoped one may close before the stream ends.
        with SessionLocal() as sdb:
            suser = sdb.get(type(user), user_id)
            sconv = sdb.get(Conversation, conv_id) if conv_id else None
            for event in run_turn(sdb, user=suser, conversation=sconv, text=payload.message, client=client):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(sse(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------------
# Stats, digest
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    return {"spend_today_usd": round(limits.spend_today_usd(db), 4), "daily_cap_usd": settings.daily_cap_usd,
            "messages_last_hour": limits.messages_last_hour(db, user.id), "rate_limit_per_hour": settings.rate_limit_per_hour}


@app.post("/internal/digest")
def digest(db: Session = Depends(get_db), x_cron_secret: str | None = Header(default=None)):
    """Manual or cron trigger for the morning digest. Protected by CRON_SECRET."""
    if not settings.cron_secret or x_cron_secret != settings.cron_secret:
        log_event("auth_failed", "warning", reason="bad_cron_secret")
        raise HTTPException(401, "Bad or missing X-Cron-Secret.")
    body = build_digest(db)
    sent = send_digest(body)
    return {"text": body, "sent": sent}

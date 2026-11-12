"""Database layer: models, engine and session.

Postgres on Railway (DATABASE_URL from the plugin) or SQLite locally. The schema is
owned by Alembic (alembic/versions); the app never creates tables itself. Every
model change needs a migration (practice.md section 6); a test fails if they drift.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    create_engine,
    text,
    Date,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A login identity: the manager or an employee. There is no self-registration; accounts are created by an
    operator (app/users.py) or, for the manager, from MANAGER_NAME / MANAGER_PASSWORD at startup."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("access_role in ('employee', 'manager')", name="ck_users_access_role"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    access_role: Mapped[str] = mapped_column(String(10), default="employee", server_default=text("'employee'"))
    code_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)  # scrypt hash; never the code
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # bump = sign out everywhere


class LoginThrottle(Base):
    """Failed-login counters and lockouts (app/throttle.py). Keys are HMACs, never names or addresses."""

    __tablename__ = "login_throttle"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)  # plain text shown in the UI
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Run(Base):
    """One model turn: the record behind the cost cap, the digest and the runbook."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | refusal | error | aborted | capped
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_names: Mapped[str] = mapped_column(String(200), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    """Append-only business audit record (app/audit.py). Written in the same transaction as the change."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # links an audit row to its log lines
    before_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)


class Shift(Base):
    """A shift definition and its staffing requirement. Configurable data, never hard-coded rules.

    `start_time` and `end_time` are wall-clock times in the business timezone (Asia/Jerusalem). When
    `end_time <= start_time` the shift ends on the NEXT calendar day, so 16:00-00:00 is eight hours and
    ends at midnight (app/shifts.py computes the real interval for a given day).
    """

    __tablename__ = "shifts"
    __table_args__ = (
        CheckConstraint("required_staff >= 0", name="ck_shifts_required_staff"),
        CheckConstraint("start_time <> end_time", name="ck_shifts_times_differ"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    required_staff: Mapped[int] = mapped_column(Integer, default=2)


class AvailabilitySubmission(Base):
    """One employee's availability and preferences for one workweek (identified by its Sunday). Latest values only."""

    __tablename__ = "availability_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_submission_user_week"),
        CheckConstraint("pref_min IS NULL OR pref_min >= 0", name="ck_submission_pref_min"),
        CheckConstraint("pref_max IS NULL OR pref_max >= 0", name="ck_submission_pref_max"),
        CheckConstraint("pref_min IS NULL OR pref_max IS NULL OR pref_min <= pref_max", name="ck_submission_pref_order"),
        CheckConstraint("free_text IS NULL OR length(free_text) <= 1000", name="ck_submission_free_text_len"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)  # always a Sunday (checked in app/cycle.py)
    pref_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pref_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    slots: Mapped[list["AvailabilitySlot"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    # (no passive_deletes: SQLite does not enforce ON DELETE CASCADE, so the ORM deletes the slots itself;
    #  PostgreSQL also has the database-level cascade for deletes that bypass the ORM)


class AvailabilitySlot(Base):
    """One shift on one day the employee can work."""

    __tablename__ = "availability_slots"
    __table_args__ = (UniqueConstraint("submission_id", "day", "shift_id", name="uq_slot_submission_day_shift"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("availability_submissions.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    submission: Mapped[AvailabilitySubmission] = relationship(back_populates="slots")


# ---------------------------------------------------------------------------
# Engine and session
# ---------------------------------------------------------------------------

def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

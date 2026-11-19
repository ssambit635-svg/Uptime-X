import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True, nullable=False)


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        UniqueConstraint("user_id", "target_fingerprint", name="uq_monitors_owner_target"),
        Index("ix_monitors_owner_paused", "user_id", "is_paused"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    expected_status_min: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    expected_status_max: Mapped[int] = mapped_column(Integer, default=299, nullable=False)
    slow_threshold_ms: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    recovery_threshold: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    regions: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["local"], nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revision_started_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
    next_check_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_manual_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class CheckJob(Base):
    __tablename__ = "check_jobs"
    __table_args__ = (
        UniqueConstraint("monitor_id", "region", "revision", "scheduled_at", name="uq_job_slot"),
        Index("ix_jobs_ready", "state", "region", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(String(40))


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"
    __table_args__ = (
        Index("ix_checks_monitor_time", "monitor_id", "scheduled_at"),
        Index("ix_checks_region_time", "region", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("check_jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    dns_ms: Mapped[float | None] = mapped_column(Float)
    connect_ms: Mapped[float | None] = mapped_column(Float)
    tls_ms: Mapped[float | None] = mapped_column(Float)
    ttfb_ms: Mapped[float | None] = mapped_column(Float)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    redirect_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(40))


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class SettingRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("key", name="key"),
        {"schema": "operations"},
    )

    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.users.id"))


class EventRecord(UUIDPrimaryKey, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_created", "created_at"),
        Index("ix_events_kind_created", "kind", "created_at"),
        {"schema": "operations"},
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.users.id"))
    kind: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message_key: Mapped[str] = mapped_column(String(200), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HealthRunRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "health_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'healthy', 'degraded', 'failed')",
            name="status_valid",
        ),
        {"schema": "operations"},
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    results: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class QueueOperationRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "queue_operations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="status_valid",
        ),
        {"schema": "operations"},
    )

    queue_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class BackupRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "backups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'restoring', 'restored', 'failed')",
            name="status_valid",
        ),
        {"schema": "operations"},
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    archive_name: Mapped[str] = mapped_column(String(500), nullable=False)
    app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    postgres_major: Mapped[int] = mapped_column(Integer, nullable=False)
    alembic_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None]
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text)

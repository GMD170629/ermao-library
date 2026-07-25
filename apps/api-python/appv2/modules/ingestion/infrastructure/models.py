from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class MonitorFolderRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "monitor_folders"
    __table_args__ = (
        UniqueConstraint("path", name="path"),
        {"schema": "ingestion"},
    )

    path: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    move_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint("idempotency_key", name="idempotency_key"),
        Index("ix_ingestion_jobs_claim", "status", "next_attempt_at", "created_at"),
        {"schema": "ingestion"},
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[uuid.UUID | None]
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)


class IngestionJobLogRecord(UUIDPrimaryKey, Base):
    __tablename__ = "job_logs"
    __table_args__ = (
        Index("ix_ingestion_job_logs_job_created", "job_id", "created_at"),
        {"schema": "ingestion"},
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion.jobs.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message_key: Mapped[str] = mapped_column(String(200), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

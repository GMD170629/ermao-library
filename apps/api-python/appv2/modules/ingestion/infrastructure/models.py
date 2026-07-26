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
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_valid"),
        UniqueConstraint(
            "idempotency_key",
            name="uq_ingestion_jobs_idempotency_key",
        ),
        Index("ix_ingestion_jobs_claim", "status", "next_attempt_at", "created_at"),
        {"schema": "ingestion"},
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.users.id"))
    monitor_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion.monitor_folders.id", ondelete="SET NULL")
    )
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_work_id: Mapped[uuid.UUID | None]
    result_edition_id: Mapped[uuid.UUID | None]
    result_volume_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class MonitorObservationRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "monitor_observations"
    __table_args__ = (
        UniqueConstraint("monitor_folder_id", "normalized_path", name="folder_path"),
        Index("ix_ingestion_observations_seen", "monitor_folder_id", "last_seen_at"),
        {"schema": "ingestion"},
    )

    monitor_folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion.monitor_folders.id", ondelete="CASCADE"), nullable=False
    )
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="file")
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion.jobs.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScanRunRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="status_valid",
        ),
        Index("ix_ingestion_scan_runs_claim", "status", "created_at"),
        {"schema": "ingestion"},
    )

    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    monitor_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion.monitor_folders.id", ondelete="CASCADE")
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.users.id"))
    directories_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ignored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionOutboxRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_ingestion_outbox_idempotency_key",
        ),
        Index("ix_ingestion_outbox_pending", "published_at", "created_at"),
        {"schema": "ingestion"},
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_detail: Mapped[str | None] = mapped_column(Text)


class IngestionPolicyRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("name", name="name"),
        {"schema": "ingestion"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    allowed_extensions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ignore_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    stability_check_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stability_check_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    auto_convert_to_epub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

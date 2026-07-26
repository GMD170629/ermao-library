from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class ProviderRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "providers"
    __table_args__ = (
        UniqueConstraint("slug", name="slug"),
        {"schema": "metadata"},
    )

    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class MetadataJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint("idempotency_key", name="idempotency_key"),
        Index("ix_metadata_jobs_claim", "status", "next_attempt_at", "created_at"),
        {"schema": "metadata"},
    )

    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.works.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("metadata.providers.id"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    query: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)


class MetadataCandidateRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "provider_id",
            "external_id",
            name="uq_candidates_job_provider_external",
        ),
        {"schema": "metadata"},
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metadata.jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metadata.providers.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class OrganizeJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "organize_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'running', 'completed', 'rejected', 'failed')",
            name="status_valid",
        ),
        Index("ix_organize_jobs_status", "status", "created_at"),
        {"schema": "metadata"},
    )

    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.works.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    proposal: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_detail: Mapped[str | None] = mapped_column(Text)


class OrganizePolicyRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "organize_policy"
    __table_args__ = (
        UniqueConstraint("name", name="uq_metadata_organize_policy_name"),
        CheckConstraint(
            "schedule_mode IN ('MANUAL', 'INTERVAL')",
            name="schedule_mode_valid",
        ),
        {"schema": "metadata"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    schedule_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    auto_run_on_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_scope: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    overwrite_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rules: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)

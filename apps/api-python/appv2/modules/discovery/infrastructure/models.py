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


class SourceRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("name", name="name"),
        {"schema": "discovery"},
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class SearchResultRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "search_results"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_search_results_source_external",
        ),
        {"schema": "discovery"},
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery.sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(500))
    download_url: Mapped[str | None] = mapped_column(Text)
    info_url: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="new")


class DownloadJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "download_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint("idempotency_key", name="idempotency_key"),
        Index("ix_download_jobs_claim", "status", "next_attempt_at", "created_at"),
        {"schema": "discovery"},
    )

    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery.search_results.id"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    destination_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)

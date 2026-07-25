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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class EmailSettingsRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "email_settings"
    __table_args__ = (
        UniqueConstraint("owner_id", name="owner"),
        {"schema": "delivery"},
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    host: Mapped[str] = mapped_column(String(500), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String(500))
    encrypted_password: Mapped[bytes | None] = mapped_column(LargeBinary)
    sender: Mapped[str] = mapped_column(String(500), nullable=False)
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class KindleSettingsRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "kindle_settings"
    __table_args__ = (
        UniqueConstraint("owner_id", name="owner"),
        {"schema": "delivery"},
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    kindle_email: Mapped[str] = mapped_column(String(500), nullable=False)
    convert_before_send: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class DeliveryJobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint("idempotency_key", name="idempotency_key"),
        Index("ix_delivery_jobs_claim", "status", "next_attempt_at", "created_at"),
        {"schema": "delivery"},
    )

    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.files.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    recipient: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)

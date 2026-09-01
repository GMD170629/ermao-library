from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default


class Source(Base):
    __tablename__ = "Source"
    __table_args__ = (
        Index("Source_enabled_idx", "enabled"),
        Index("Source_kind_idx", "kind"),
        Index("Source_providerType_idx", "providerType"),
        Index("Source_priority_idx", "priority"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    kind: Mapped[str] = mapped_column(String(191), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        "providerType", String(191), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_key: Mapped[str | None] = mapped_column(
        "credentialsKey", String(191), nullable=True
    )
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit: Mapped[str | None] = mapped_column("rateLimit", Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(
        "lastTestAt", TimestampMilliseconds(), nullable=True
    )
    last_test_status: Mapped[str | None] = mapped_column(
        "lastTestStatus", String(191), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column("lastError", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class SourceSearchRecord(Base):
    __tablename__ = "SourceSearchRecord"
    __table_args__ = (
        Index("SourceSearchRecord_sourceId_idx", "sourceId"),
        Index("SourceSearchRecord_providerType_idx", "providerType"),
        Index("SourceSearchRecord_status_idx", "status"),
        Index("SourceSearchRecord_title_idx", "title"),
        Index("SourceSearchRecord_createdAt_idx", "createdAt"),
        UniqueConstraint(
            "sourceId", "externalId", name="SourceSearchRecord_sourceId_externalId_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    source_id: Mapped[str] = mapped_column(
        "sourceId",
        String(191),
        ForeignKey("Source.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    provider_type: Mapped[str] = mapped_column(
        "providerType", String(191), nullable=False
    )
    external_id: Mapped[str] = mapped_column("externalId", String(191), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column("coverUrl", Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column("externalUrl", Text, nullable=True)
    format: Mapped[str | None] = mapped_column(String(191), nullable=True)
    size: Mapped[str | None] = mapped_column(String(191), nullable=True)
    language: Mapped[str | None] = mapped_column(String(191), nullable=True)
    published_at: Mapped[str | None] = mapped_column(
        "publishedAt", String(191), nullable=True
    )
    download_available: Mapped[bool] = mapped_column(
        "downloadAvailable", Boolean, nullable=False, default=False, server_default="0"
    )
    download_meta: Mapped[str | None] = mapped_column(
        "downloadMeta", Text, nullable=True
    )
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="new", server_default="new"
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class DownloadTask(Base):
    __tablename__ = "DownloadTask"
    __table_args__ = (
        Index("DownloadTask_sourceId_idx", "sourceId"),
        Index("DownloadTask_searchRecordId_idx", "searchRecordId"),
        Index("DownloadTask_bookId_idx", "bookId"),
        Index("DownloadTask_type_idx", "type"),
        Index("DownloadTask_status_createdAt_idx", "status", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    source_id: Mapped[str | None] = mapped_column(
        "sourceId", String(191), nullable=True
    )
    search_record_id: Mapped[str | None] = mapped_column(
        "searchRecordId", String(191), nullable=True
    )
    book_id: Mapped[str | None] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column("type", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column("displayName", Text, nullable=False)
    remote_ref: Mapped[str | None] = mapped_column("remoteRef", Text, nullable=True)
    save_path: Mapped[str | None] = mapped_column("savePath", Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column("filePath", Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        "errorMessage", Text, nullable=True
    )
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class KindleSendTask(Base):
    __tablename__ = "KindleSendTask"
    __table_args__ = (
        Index(
            "KindleSendTask_status_nextAttemptAt_createdAt_idx",
            "status",
            "nextAttemptAt",
            "createdAt",
        ),
        Index("KindleSendTask_bookId_createdAt_idx", "bookId", "createdAt"),
        Index("KindleSendTask_userId_createdAt_idx", "userId", "createdAt"),
        Index("KindleSendTask_resourceId_idx", "resourceId"),
        Index("KindleSendTask_assetId_idx", "assetId"),
        Index(
            "KindleSendTask_active_asset_recipient_key",
            "assetId",
            "recipientEmail",
            unique=True,
            sqlite_where=column("status").in_(("queued", "sending")),
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str | None] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    book_id: Mapped[str | None] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    resource_id: Mapped[str | None] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="SET NULL", onupdate="CASCADE"
        ),
        nullable=True,
    )
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        String(191),
        ForeignKey("LibraryResourceAsset.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    book_title: Mapped[str] = mapped_column("bookTitle", Text, nullable=False)
    resource_title: Mapped[str | None] = mapped_column(
        "resourceTitle", Text, nullable=True
    )
    file_name: Mapped[str] = mapped_column("fileName", Text, nullable=False)
    format: Mapped[str] = mapped_column(String(191), nullable=False)
    mime_type: Mapped[str] = mapped_column("mimeType", String(191), nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        "sizeBytes", Integer, nullable=False, default=0, server_default="0"
    )
    sender_email: Mapped[str | None] = mapped_column(
        "senderEmail", String(191), nullable=True
    )
    recipient_email: Mapped[str] = mapped_column(
        "recipientEmail", String(191), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    smtp_host: Mapped[str | None] = mapped_column(
        "smtpHost", String(191), nullable=True
    )
    smtp_port: Mapped[int | None] = mapped_column("smtpPort", Integer, nullable=True)
    smtp_security: Mapped[str | None] = mapped_column(
        "smtpSecurity", String(191), nullable=True
    )
    smtp_username: Mapped[str | None] = mapped_column(
        "smtpUsername", String(191), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        "messageId", String(191), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    attempt_count: Mapped[int] = mapped_column(
        "attemptCount", Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        "nextAttemptAt", TimestampMilliseconds(), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(
        "errorMessage", Text, nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        "sentAt", TimestampMilliseconds(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


__all__ = ["DownloadTask", "KindleSendTask", "Source", "SourceSearchRecord"]

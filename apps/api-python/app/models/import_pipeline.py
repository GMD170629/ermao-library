from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
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
    book_id: Mapped[str | None] = mapped_column("bookId", String(191), nullable=True)
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
        Index("KindleSendTask_workId_createdAt_idx", "workId", "createdAt"),
        Index("KindleSendTask_userId_createdAt_idx", "userId", "createdAt"),
        Index(
            "KindleSendTask_active_file_recipient_key",
            "fileId",
            "recipientEmail",
            unique=True,
            sqlite_where=column("status", String).in_(("queued", "sending")),
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str | None] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    work_id: Mapped[str | None] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    edition_id: Mapped[str | None] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    volume_id: Mapped[str | None] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    file_id: Mapped[str | None] = mapped_column(
        "fileId",
        String(191),
        ForeignKey("LibraryFile.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    book_title: Mapped[str] = mapped_column("bookTitle", Text, nullable=False)
    edition_name: Mapped[str | None] = mapped_column("editionName", Text, nullable=True)
    volume_title: Mapped[str | None] = mapped_column("volumeTitle", Text, nullable=True)
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


class ImportTask(Base):
    __tablename__ = "ImportTask"
    __table_args__ = (
        Index("ImportTask_monitorFolderId_status_idx", "monitorFolderId", "status"),
        Index("ImportTask_status_createdAt_idx", "status", "createdAt"),
        Index("ImportTask_contentHash_idx", "contentHash"),
        Index("ImportTask_workId_idx", "workId"),
        Index("ImportTask_editionId_idx", "editionId"),
        Index("ImportTask_volumeId_idx", "volumeId"),
        Index("ImportTask_status_leaseExpiresAt_idx", "status", "leaseExpiresAt"),
        Index("ImportTask_createdAt_id_idx", "createdAt", "id"),
        Index(
            "ImportTask_sourceKey_status_createdAt_idx",
            "sourceKey",
            "status",
            "createdAt",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    monitor_folder_id: Mapped[str | None] = mapped_column(
        "monitorFolderId",
        String(191),
        ForeignKey("MonitorFolder.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    work_id: Mapped[str | None] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    edition_id: Mapped[str | None] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    volume_id: Mapped[str | None] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    origin: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    original_name: Mapped[str | None] = mapped_column(
        "originalName", Text, nullable=True
    )
    requested_title: Mapped[str | None] = mapped_column(
        "requestedTitle", Text, nullable=True
    )
    requested_author: Mapped[str | None] = mapped_column(
        "requestedAuthor", Text, nullable=True
    )
    source_path: Mapped[str] = mapped_column("sourcePath", Text, nullable=False)
    source_key: Mapped[str | None] = mapped_column(
        "sourceKey", String(64), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(
        "contentHash", String(191), nullable=True
    )
    task_kind: Mapped[str] = mapped_column(
        "taskKind", String(191), nullable=False, default="FILE", server_default="FILE"
    )
    bundle_key: Mapped[str | None] = mapped_column(
        "bundleKey", String(191), nullable=True
    )
    asset_count: Mapped[int] = mapped_column(
        "assetCount", Integer, nullable=False, default=1, server_default="1"
    )
    processed_asset_count: Mapped[int] = mapped_column(
        "processedAssetCount", Integer, nullable=False, default=0, server_default="0"
    )
    progress: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    duration: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_summary: Mapped[str | None] = mapped_column(
        "errorSummary", Text, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(
        "errorCode", String(191), nullable=True
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(
        "leaseOwner", String(191), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", TimestampMilliseconds(), nullable=True
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        "finishedAt", TimestampMilliseconds(), nullable=True
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


class ImportScanJob(Base):
    __tablename__ = "ImportScanJob"
    __table_args__ = (
        Index(
            "ImportScanJob_monitorFolderId_status_createdAt_idx",
            "monitorFolderId",
            "status",
            "createdAt",
        ),
        Index("ImportScanJob_status_updatedAt_idx", "status", "updatedAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    monitor_folder_id: Mapped[str | None] = mapped_column(
        "monitorFolderId",
        String(191),
        ForeignKey("MonitorFolder.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        "actorUserId",
        String(191),
        ForeignKey("User.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    root_path: Mapped[str] = mapped_column("rootPath", Text, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    directories_scanned: Mapped[int] = mapped_column(
        "directoriesScanned", Integer, nullable=False, default=0, server_default="0"
    )
    files_scanned: Mapped[int] = mapped_column(
        "filesScanned", Integer, nullable=False, default=0, server_default="0"
    )
    candidates_found: Mapped[int] = mapped_column(
        "candidatesFound", Integer, nullable=False, default=0, server_default="0"
    )
    queued_count: Mapped[int] = mapped_column(
        "queuedCount", Integer, nullable=False, default=0, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        "skippedCount", Integer, nullable=False, default=0, server_default="0"
    )
    error_count: Mapped[int] = mapped_column(
        "errorCount", Integer, nullable=False, default=0, server_default="0"
    )
    ignored_reason_counts: Mapped[dict[str, int]] = mapped_column(
        "ignoredReasonCounts", JSON, nullable=False, default=dict, server_default="{}"
    )
    error_samples: Mapped[list[dict[str, str]]] = mapped_column(
        "errorSamples", JSON, nullable=False, default=list, server_default="[]"
    )
    restart_count: Mapped[int] = mapped_column(
        "restartCount", Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        "heartbeatAt", TimestampMilliseconds(), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        "finishedAt", TimestampMilliseconds(), nullable=True
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


class ImportWorkItem(Base):
    __tablename__ = "ImportWorkItem"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'SCAN_DIRECTORY' AND scanJobId IS NOT NULL "
            "AND importTaskId IS NULL) OR "
            "(kind = 'IMPORT_SOURCE' AND importTaskId IS NOT NULL "
            "AND scanJobId IS NULL)",
            name="ImportWorkItem_target_check",
        ),
        UniqueConstraint("dedupeKey", name="ImportWorkItem_dedupeKey_key"),
        UniqueConstraint("scanJobId", name="ImportWorkItem_scanJobId_key"),
        UniqueConstraint("importTaskId", name="ImportWorkItem_importTaskId_key"),
        Index(
            "ImportWorkItem_status_availableAt_priority_createdAt_idx",
            "status",
            "availableAt",
            "priority",
            "createdAt",
        ),
        Index("ImportWorkItem_kind_status_idx", "kind", "status"),
        Index("ImportWorkItem_leaseExpiresAt_idx", "leaseExpiresAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scan_job_id: Mapped[str | None] = mapped_column(
        "scanJobId",
        String(191),
        ForeignKey("ImportScanJob.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    import_task_id: Mapped[str | None] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    dedupe_key: Mapped[str] = mapped_column("dedupeKey", String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    available_at: Mapped[datetime] = mapped_column(
        "availableAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    lease_owner: Mapped[str | None] = mapped_column(
        "leaseOwner", String(191), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        "leaseExpiresAt", TimestampMilliseconds(), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class ImportAsset(Base):
    __tablename__ = "ImportAsset"
    __table_args__ = (
        Index("ImportAsset_importTaskId_sortOrder_idx", "importTaskId", "sortOrder"),
        UniqueConstraint(
            "importTaskId", "sourcePath", name="ImportAsset_importTaskId_sourcePath_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    import_task_id: Mapped[str] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column("sourcePath", Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    sort_order: Mapped[int] = mapped_column(
        "sortOrder", Integer, nullable=False, default=0, server_default="0"
    )
    file_id: Mapped[str | None] = mapped_column(
        "fileId",
        String(191),
        ForeignKey("LibraryFile.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(
        "errorCode", String(191), nullable=True
    )
    error_summary: Mapped[str | None] = mapped_column(
        "errorSummary", Text, nullable=True
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


class BookConversionTask(Base):
    __tablename__ = "BookConversionTask"
    __table_args__ = (
        UniqueConstraint("importTaskId"),
        Index("BookConversionTask_status_createdAt_idx", "status", "createdAt"),
        Index("BookConversionTask_sourceHash_idx", "sourceHash"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    import_task_id: Mapped[str] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(191), nullable=False, default="AUTO", server_default="AUTO"
    )
    source_format: Mapped[str] = mapped_column(
        "sourceFormat", String(191), nullable=False
    )
    target_format: Mapped[str] = mapped_column(
        "targetFormat",
        String(191),
        nullable=False,
        default="EPUB",
        server_default="EPUB",
    )
    source_path: Mapped[str] = mapped_column("sourcePath", Text, nullable=False)
    output_path: Mapped[str | None] = mapped_column("outputPath", Text, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(
        "sourceHash", String(191), nullable=True
    )
    converter: Mapped[str] = mapped_column(
        String(191),
        nullable=False,
        default="shuku-internal",
        server_default="shuku-internal",
    )
    converter_version: Mapped[str | None] = mapped_column(
        "converterVersion", String(191), nullable=True
    )
    options_json: Mapped[str] = mapped_column(
        "optionsJson", Text, nullable=False, default="{}", server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="QUEUED", server_default="QUEUED"
    )
    progress: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(
        "errorCode", String(191), nullable=True
    )
    error_summary: Mapped[str | None] = mapped_column(
        "errorSummary", Text, nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        "finishedAt", TimestampMilliseconds(), nullable=True
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


class ImportLog(Base):
    __tablename__ = "ImportLog"
    __table_args__ = (
        Index("ImportLog_importTaskId_createdAt_idx", "importTaskId", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    import_task_id: Mapped[str] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(
        String(191), nullable=False, default="info", server_default="info"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )

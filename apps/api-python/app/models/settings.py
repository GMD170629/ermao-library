from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import timestamp_ms_server_default


def cuid() -> str:
    return f"py_{uuid4().hex}"


def db_timestamp() -> datetime:
    return datetime.now(timezone.utc)


class MonitorFolder(Base):
    __tablename__ = "MonitorFolder"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    root_path: Mapped[str] = mapped_column("rootPath", String(191), unique=True, nullable=False)
    shelf_id: Mapped[str | None] = mapped_column(
        "shelfId",
        String(191),
        ForeignKey("Shelf.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    ignore_patterns: Mapped[str | None] = mapped_column("ignorePatterns", Text, nullable=True)
    ignore_hidden: Mapped[bool] = mapped_column("ignoreHidden", Boolean, nullable=False, default=True, server_default="1")
    min_file_size_bytes: Mapped[int] = mapped_column("minFileSizeBytes", Integer, nullable=False, default=10240, server_default="10240")
    description: Mapped[str | None] = mapped_column(String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class SystemSetting(Base):
    __tablename__ = "SystemSetting"

    key: Mapped[str] = mapped_column(String(191), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class BookIdentityCache(Base):
    __tablename__ = "BookIdentityCache"
    __table_args__ = (Index("BookIdentityCache_parserVersion_idx", "parserVersion"),)

    logical_path: Mapped[str] = mapped_column("logicalPath", Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    volume_index: Mapped[float | None] = mapped_column("volumeIndex", Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    parser_version: Mapped[int] = mapped_column("parserVersion", Integer, nullable=False)
    raw_json: Mapped[str] = mapped_column("rawJson", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class SystemEvent(Base):
    __tablename__ = "SystemEvent"
    __table_args__ = (
        Index("SystemEvent_level_createdAt_idx", "level", "createdAt"),
        Index("SystemEvent_source_createdAt_idx", "source", "createdAt"),
        Index("SystemEvent_actorType_createdAt_idx", "actorType", "createdAt"),
        Index("SystemEvent_action_createdAt_idx", "action", "createdAt"),
        Index("SystemEvent_targetType_targetId_idx", "targetType", "targetId"),
        Index("SystemEvent_createdAt_idx", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    level: Mapped[str] = mapped_column(String(191), nullable=False, default="info", server_default="info")
    source: Mapped[str] = mapped_column(String(191), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        "actorType",
        String(191),
        nullable=False,
        default="system",
        server_default="system",
    )
    actor_id: Mapped[str | None] = mapped_column("actorId", String(191), nullable=True)
    action: Mapped[str] = mapped_column(String(191), nullable=False)
    target_type: Mapped[str | None] = mapped_column("targetType", String(191), nullable=True)
    target_id: Mapped[str | None] = mapped_column("targetId", String(191), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )


class SystemHealthRun(Base):
    __tablename__ = "SystemHealthRun"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    actor_user_id: Mapped[str] = mapped_column("actorUserId", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column("startedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class QueueRuntimeState(Base):
    __tablename__ = "QueueRuntimeState"

    queue_name: Mapped[str] = mapped_column("queueName", String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column("instanceId", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    poll_interval_seconds: Mapped[float] = mapped_column("pollIntervalSeconds", Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column("startedAt", TimestampMilliseconds(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column("heartbeatAt", TimestampMilliseconds(), nullable=False)
    last_processed_at: Mapped[datetime | None] = mapped_column("lastProcessedAt", TimestampMilliseconds(), nullable=True)
    last_error: Mapped[str | None] = mapped_column("lastError", Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False)


class QueueControlOperation(Base):
    __tablename__ = "QueueControlOperation"
    __table_args__ = (
        Index("QueueControlOperation_queue_status_idx", "queueName", "status", "requestedAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    queue_name: Mapped[str] = mapped_column("queueName", String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str] = mapped_column("actorUserId", String(191), nullable=False)
    message_code: Mapped[str | None] = mapped_column("messageCode", String(191), nullable=True)
    requested_at: Mapped[datetime] = mapped_column("requestedAt", TimestampMilliseconds(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TimestampMilliseconds(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False)


class ReaderPreference(Base):
    __tablename__ = "ReaderPreference"
    __table_args__ = (
        Index("ReaderPreference_userId_idx", "userId"),
        UniqueConstraint("userId", "readerType", name="ReaderPreference_userId_readerType_key"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    reader_type: Mapped[str] = mapped_column("readerType", String(191), nullable=False)
    settings: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class ReaderBookPreference(Base):
    """Versioned server default for one user's view of one library work."""

    __tablename__ = "ReaderBookPreference"
    __table_args__ = (UniqueConstraint("userId", "workId", name="ReaderBookPreference_userId_workId_key"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column("userId", String(191), ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[int] = mapped_column("schemaVersion", Integer, nullable=False, default=3, server_default="3")
    preferences: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class ReaderProgressCursor(Base):
    """Durable per-client high-water mark for monotonic reader progress."""

    __tablename__ = "ReaderProgressCursor"
    __table_args__ = (UniqueConstraint("userId", "workId", "clientId", name="ReaderProgressCursor_userId_workId_clientId_key"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column("userId", String(191), ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column("clientId", String(191), nullable=False)
    high_water: Mapped[int] = mapped_column(
        "highWater",
        BigInteger,
        nullable=False,
        default=-1,
        server_default="-1",
    )
    last_mutation_id: Mapped[str | None] = mapped_column("lastMutationId", String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)

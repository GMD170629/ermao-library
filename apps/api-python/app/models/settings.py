from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import timestamp_ms_server_default


def cuid() -> str:
    return f"py_{uuid4().hex}"


def db_timestamp() -> datetime:
    return datetime.now(timezone.utc)


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
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class SystemEvent(Base):
    __tablename__ = "SystemEvent"
    __table_args__ = (
        Index("SystemEvent_level_createdAt_idx", "level", "createdAt"),
        Index("SystemEvent_source_createdAt_idx", "source", "createdAt"),
        Index("SystemEvent_actorType_createdAt_idx", "actorType", "createdAt"),
        Index("SystemEvent_action_createdAt_idx", "action", "createdAt"),
        Index("SystemEvent_targetType_targetId_idx", "targetType", "targetId"),
        Index("SystemEvent_createdAt_idx", "createdAt"),
        Index("SystemEvent_createdAt_id_idx", "createdAt", "id"),
        Index(
            "SystemEvent_targetType_createdAt_id_idx",
            "targetType",
            "createdAt",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    level: Mapped[str] = mapped_column(
        String(191), nullable=False, default="info", server_default="info"
    )
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
    target_type: Mapped[str | None] = mapped_column(
        "targetType", String(191), nullable=True
    )
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
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp
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


class QueueRuntimeState(Base):
    """Process-level runtime status retained independently of import tasks."""

    __tablename__ = "QueueRuntimeState"

    queue_name: Mapped[str] = mapped_column("queueName", String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column("instanceId", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    poll_interval_seconds: Mapped[float] = mapped_column(
        "pollIntervalSeconds", Float, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        "heartbeatAt", TimestampMilliseconds(), nullable=False
    )
    last_processed_at: Mapped[datetime | None] = mapped_column(
        "lastProcessedAt", TimestampMilliseconds(), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column("lastError", Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", TimestampMilliseconds(), nullable=False
    )


class ReaderPreference(Base):
    __tablename__ = "ReaderPreference"
    __table_args__ = (
        Index("ReaderPreference_userId_idx", "userId"),
        UniqueConstraint(
            "userId", "readerType", name="ReaderPreference_userId_readerType_key"
        ),
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
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class ReaderBookPreference(Base):
    """Versioned server default for one user's view of one book."""

    __tablename__ = "ReaderBookPreference"
    __table_args__ = (
        UniqueConstraint(
            "userId", "bookId", name="ReaderBookPreference_userId_bookId_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    book_id: Mapped[str] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[int] = mapped_column(
        "schemaVersion", Integer, nullable=False, default=3, server_default="3"
    )
    preferences: Mapped[str] = mapped_column(Text, nullable=False)
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

    user: Mapped["User"] = relationship("User")
    book: Mapped["LibraryBook"] = relationship("LibraryBook")


class ReaderProgressCursor(Base):
    """Durable per-client high-water mark for monotonic resource progress."""

    __tablename__ = "ReaderProgressCursor"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "resourceId",
            "clientId",
            name="ReaderProgressCursor_userId_resourceId_clientId_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column("clientId", String(191), nullable=False)
    high_water: Mapped[int] = mapped_column(
        "highWater", BigInteger, nullable=False, default=-1, server_default="-1"
    )
    last_mutation_id: Mapped[str | None] = mapped_column(
        "lastMutationId", String(191), nullable=True
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

    user: Mapped["User"] = relationship("User")
    resource: Mapped["LibraryReadableResource"] = relationship(
        "LibraryReadableResource"
    )


__all__ = [
    "QueueRuntimeState",
    "ReaderBookPreference",
    "ReaderPreference",
    "ReaderProgressCursor",
    "SystemEvent",
    "SystemHealthRun",
    "SystemSetting",
]

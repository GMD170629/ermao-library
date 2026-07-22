from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def cuid() -> str:
    return f"py_{uuid4().hex}"


def db_timestamp() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MonitorFolder(Base):
    __tablename__ = "MonitorFolder"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    root_path: Mapped[str] = mapped_column("rootPath", String(191), unique=True, nullable=False)
    shelf_id: Mapped[str | None] = mapped_column("shelfId", String(191), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ignore_patterns: Mapped[str | None] = mapped_column("ignorePatterns", Text, nullable=True)
    ignore_hidden: Mapped[bool] = mapped_column("ignoreHidden", Boolean, nullable=False, default=True)
    min_file_size_bytes: Mapped[int] = mapped_column("minFileSizeBytes", Integer, nullable=False, default=10240)
    description: Mapped[str | None] = mapped_column(String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False, default=db_timestamp, onupdate=db_timestamp, server_default=func.now())


class SystemSetting(Base):
    __tablename__ = "SystemSetting"

    key: Mapped[str] = mapped_column(String(191), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False, default=db_timestamp, onupdate=db_timestamp, server_default=func.now())


class BookIdentityCache(Base):
    __tablename__ = "BookIdentityCache"

    logical_path: Mapped[str] = mapped_column("logicalPath", Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    volume_index: Mapped[float | None] = mapped_column("volumeIndex", Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    parser_version: Mapped[int] = mapped_column("parserVersion", Integer, nullable=False)
    raw_json: Mapped[str] = mapped_column("rawJson", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False, default=db_timestamp, onupdate=db_timestamp, server_default=func.now())


class SystemEvent(Base):
    __tablename__ = "SystemEvent"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    level: Mapped[str] = mapped_column(String(191), nullable=False, default="info")
    source: Mapped[str] = mapped_column(String(191), nullable=False)
    actor_type: Mapped[str] = mapped_column("actorType", String(191), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column("actorId", String(191), nullable=True)
    action: Mapped[str] = mapped_column(String(191), nullable=False)
    target_type: Mapped[str | None] = mapped_column("targetType", String(191), nullable=True)
    target_id: Mapped[str | None] = mapped_column("targetId", String(191), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())


class ReaderBookPreference(Base):
    """Versioned server default for one user's view of one library work.

    LibraryWork is managed by the compatibility schema instead of SQLAlchemy
    metadata in tests, so only the User foreign key is declared here. The
    production schema declares both foreign keys.
    """

    __tablename__ = "ReaderBookPreference"
    __table_args__ = (UniqueConstraint("userId", "workId", name="ReaderBookPreference_userId_workId_key"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column("userId", String(191), ForeignKey("User.id", ondelete="CASCADE"), nullable=False, index=True)
    work_id: Mapped[str] = mapped_column("workId", String(191), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column("schemaVersion", Integer, nullable=False, default=3, server_default="3")
    preferences: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False, default=db_timestamp, onupdate=db_timestamp, server_default=func.now())


class ReaderProgressCursor(Base):
    """Durable per-client high-water mark for monotonic reader progress."""

    __tablename__ = "ReaderProgressCursor"
    __table_args__ = (UniqueConstraint("userId", "workId", "clientId", name="ReaderProgressCursor_userId_workId_clientId_key"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column("userId", String(191), ForeignKey("User.id", ondelete="CASCADE"), nullable=False, index=True)
    work_id: Mapped[str] = mapped_column("workId", String(191), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column("clientId", String(191), nullable=False)
    high_water: Mapped[int] = mapped_column("highWater", BigInteger, nullable=False, default=-1)
    last_mutation_id: Mapped[str | None] = mapped_column("lastMutationId", String(191), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False, default=db_timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False, default=db_timestamp, onupdate=db_timestamp, server_default=func.now())

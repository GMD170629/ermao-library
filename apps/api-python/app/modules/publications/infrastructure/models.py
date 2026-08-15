"""SQLAlchemy persistence model for successful Publication navigation caches."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import db_timestamp, timestamp_ms_server_default
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
)


class PublicationNavigationCache(Base):
    __tablename__ = "PublicationNavigationCache"
    __table_args__ = (
        CheckConstraint(
            '"chapterCount" >= 0',
            name="PublicationNavigationCache_chapterCount_check",
        ),
    )

    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[str] = mapped_column(
        "fileId",
        String(191),
        ForeignKey("LibraryFile.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_size_bytes: Mapped[int] = mapped_column("sourceSizeBytes", Integer, nullable=False)
    source_mtime_ms: Mapped[int] = mapped_column("sourceMtimeMs", Integer, nullable=False)
    parser: Mapped[str] = mapped_column(String(191), nullable=False)
    normalization: Mapped[str] = mapped_column(String(191), nullable=False)
    projection_version: Mapped[int] = mapped_column(
        "projectionVersion",
        Integer,
        nullable=False,
        default=CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    )
    chapter_count: Mapped[int] = mapped_column("chapterCount", Integer, nullable=False)
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


class PublicationRenderCache(Base):
    __tablename__ = "PublicationRenderCache"
    __table_args__ = (
        CheckConstraint(
            '"sizeBytes" > 0',
            name="PublicationRenderCache_sizeBytes_check",
        ),
        CheckConstraint(
            '"unreadableResourceCount" >= 0',
            name="PublicationRenderCache_unreadableResourceCount_check",
        ),
    )

    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[str] = mapped_column(
        "fileId",
        String(191),
        ForeignKey("LibraryFile.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_size_bytes: Mapped[int] = mapped_column("sourceSizeBytes", Integer, nullable=False)
    source_mtime_ms: Mapped[int] = mapped_column("sourceMtimeMs", Integer, nullable=False)
    parser: Mapped[str] = mapped_column(String(191), nullable=False)
    normalization: Mapped[str] = mapped_column(String(191), nullable=False)
    relative_path: Mapped[str] = mapped_column(
        "relativePath", String(1024), nullable=False
    )
    size_bytes: Mapped[int] = mapped_column("sizeBytes", Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="READY")
    unreadable_resource_count: Mapped[int] = mapped_column(
        "unreadableResourceCount", Integer, nullable=False, default=0
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


__all__ = ["PublicationNavigationCache", "PublicationRenderCache"]

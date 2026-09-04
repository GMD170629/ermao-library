"""SQLAlchemy models owned by the isolated Reader v5 persistence adapter."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import ExactTimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default


class ReaderResourceProgressV5(Base):
    """Opaque Reader v5 position plus the client-owned presentation."""

    __tablename__ = "ReaderResourceProgressV5"
    __table_args__ = (
        Index("ReaderResourceProgressV5_resourceId_idx", "resourceId"),
        Index(
            "ReaderResourceProgressV5_userId_updatedAt_resourceId_idx",
            "userId",
            "updatedAt",
            "resourceId",
        ),
        Index(
            "ReaderResourceProgressV5_userId_resourceId_key",
            "userId",
            "resourceId",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    client_id: Mapped[str] = mapped_column("clientId", String(256), nullable=False)
    mutation_id: Mapped[str] = mapped_column("mutationId", String(36), nullable=False)
    locator_json: Mapped[str] = mapped_column("locatorJson", Text, nullable=False)
    presentation_json: Mapped[str] = mapped_column(
        "presentationJson", Text, nullable=False
    )
    display_percent: Mapped[float] = mapped_column(
        "displayPercent", Float, nullable=False, default=0
    )
    total_progression: Mapped[float] = mapped_column(
        "totalProgression", Float, nullable=False, default=0
    )
    current_href: Mapped[str | None] = mapped_column(
        "currentHref", String(8192), nullable=True
    )
    chapter_href: Mapped[str | None] = mapped_column(
        "chapterHref", String(8192), nullable=True
    )
    chapter_title: Mapped[str | None] = mapped_column(
        "chapterTitle", String(4096), nullable=True
    )
    chapter_index: Mapped[int | None] = mapped_column(
        "chapterIndex", Integer, nullable=True
    )
    page_number: Mapped[int | None] = mapped_column(
        "pageNumber", Integer, nullable=True
    )
    page_total: Mapped[int | None] = mapped_column("pageTotal", Integer, nullable=True)
    playback_position_millis: Mapped[int | None] = mapped_column(
        "playbackPositionMillis", Integer, nullable=True
    )
    playback_duration_millis: Mapped[int | None] = mapped_column(
        "playbackDurationMillis", Integer, nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        "capturedAt", ExactTimestampMilliseconds(), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        "receivedAt",
        ExactTimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        ExactTimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
        onupdate=db_timestamp,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReaderProgressMutationV5(Base):
    """Digest-only idempotency receipt for an opaque v5 position report."""

    __tablename__ = "ReaderProgressMutationV5"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "resourceId",
            "mutationId",
            name="ReaderProgressMutationV5_userId_resourceId_mutationId_key",
        ),
        Index(
            "ReaderProgressMutationV5_userId_resourceId_acceptedRevision_idx",
            "userId",
            "resourceId",
            "acceptedRevision",
        ),
        Index("ReaderProgressMutationV5_resourceId_idx", "resourceId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    mutation_id: Mapped[str] = mapped_column("mutationId", String(36), nullable=False)
    client_id: Mapped[str] = mapped_column("clientId", String(256), nullable=False)
    accepted_revision: Mapped[int] = mapped_column(
        "acceptedRevision", Integer, nullable=False
    )
    payload_hash: Mapped[str] = mapped_column("payloadHash", String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        "capturedAt", ExactTimestampMilliseconds(), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        "receivedAt", ExactTimestampMilliseconds(), nullable=False
    )


class ReaderResourceReadingStatusV5(Base):
    """Independent v5 reading status; it never manufactures a progress row."""

    __tablename__ = "ReaderResourceReadingStatusV5"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "resourceId",
            name="ReaderResourceReadingStatusV5_userId_resourceId_key",
        ),
        Index("ReaderResourceReadingStatusV5_resourceId_idx", "resourceId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column("status", String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        ExactTimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
        onupdate=db_timestamp,
    )


class ReaderBookmarkV5(Base):
    """Opaque Reader v5 bookmarks, isolated from the retired v4 rows."""

    __tablename__ = "ReaderBookmarkV5"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "resourceId",
            "bookmarkId",
            name="ReaderBookmarkV5_user_resource_bookmark_key",
        ),
        Index(
            "ReaderBookmarkV5_user_resource_createdAt_bookmarkId_idx",
            "userId",
            "resourceId",
            "bookmarkCreatedAt",
            "bookmarkId",
        ),
        Index("ReaderBookmarkV5_resourceId_idx", "resourceId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    bookmark_id: Mapped[str] = mapped_column("bookmarkId", String(5000), nullable=False)
    locator_json: Mapped[str] = mapped_column("locatorJson", Text, nullable=False)
    presentation_json: Mapped[str] = mapped_column(
        "presentationJson", Text, nullable=False
    )
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    bookmark_created_at: Mapped[datetime] = mapped_column(
        "bookmarkCreatedAt", ExactTimestampMilliseconds(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        ExactTimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        ExactTimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
        onupdate=db_timestamp,
    )


__all__ = [
    "ReaderBookmarkV5",
    "ReaderProgressMutationV5",
    "ReaderResourceProgressV5",
    "ReaderResourceReadingStatusV5",
]

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class Library(Base):
    __tablename__ = "Library"
    __table_args__ = (
        CheckConstraint(
            column("organizationMode").in_(("FLAT", "VOLUMES")),
            name="Library_organizationMode_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    root_path: Mapped[str] = mapped_column(
        "rootPath", String(191), unique=True, nullable=False
    )
    organization_mode: Mapped[str] = mapped_column(
        "organizationMode", String(32), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    ignore_patterns: Mapped[str | None] = mapped_column(
        "ignorePatterns", Text, nullable=True
    )
    ignore_hidden: Mapped[bool] = mapped_column(
        "ignoreHidden", Boolean, nullable=False, default=True, server_default="1"
    )
    min_file_size_bytes: Mapped[int] = mapped_column(
        "minFileSizeBytes",
        Integer,
        nullable=False,
        default=10240,
        server_default="10240",
    )
    description: Mapped[str | None] = mapped_column(String(191), nullable=True)
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


class LibraryFacet(Base):
    """A normalized facet dictionary shared by book/resource links."""

    __tablename__ = "LibraryFacet"
    __table_args__ = (
        UniqueConstraint("kind", "normalizedName"),
        Index("LibraryFacet_kind_name_idx", "kind", "name"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    kind: Mapped[str] = mapped_column(String(191), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column("normalizedName", Text, nullable=False)
    aliases: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
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


class LibraryBookFacet(Base):
    __tablename__ = "LibraryBookFacet"
    __table_args__ = (Index("LibraryBookFacet_bookId_idx", "bookId"),)

    facet_id: Mapped[str] = mapped_column(
        "facetId",
        String(191),
        ForeignKey("LibraryFacet.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    book_id: Mapped[str] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    sort_order: Mapped[int] = mapped_column(
        "sortOrder", Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )


class LibraryReadableResourceFacet(Base):
    __tablename__ = "LibraryReadableResourceFacet"
    __table_args__ = (
        Index("LibraryReadableResourceFacet_resourceId_idx", "resourceId"),
    )

    facet_id: Mapped[str] = mapped_column(
        "facetId",
        String(191),
        ForeignKey("LibraryFacet.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )


class LibraryOperation(Base):
    __tablename__ = "LibraryOperation"
    __table_args__ = (
        Index("LibraryOperation_action_createdAt_idx", "action", "createdAt"),
        Index("LibraryOperation_status_expiresAt_idx", "status", "expiresAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str | None] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(191), nullable=False, default="COMPLETED", server_default="COMPLETED"
    )
    target_type: Mapped[str | None] = mapped_column(
        "targetType", String(191), nullable=True
    )
    target_id: Mapped[str | None] = mapped_column(
        "targetId", String(191), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(
        "payloadJson", Text, nullable=False, default="{}", server_default="{}"
    )
    inverse_json: Mapped[str] = mapped_column(
        "inverseJson", Text, nullable=False, default="{}", server_default="{}"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        "expiresAt", TimestampMilliseconds(), nullable=True
    )
    undone_at: Mapped[datetime | None] = mapped_column(
        "undoneAt", TimestampMilliseconds(), nullable=True
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


class ReadableResourceNavigationUnit(Base):
    __tablename__ = "ReadableResourceNavigationUnit"
    __table_args__ = (
        Index(
            "ReadableResourceNavigationUnit_resourceId_sortOrder_idx",
            "resourceId",
            "sortOrder",
        ),
        Index(
            "ReadableResourceNavigationUnit_assetId_sortOrder_idx",
            "assetId",
            "sortOrder",
        ),
        UniqueConstraint(
            "resourceId",
            "unitType",
            "sortOrder",
            name="ReadableResourceNavigationUnit_resourceId_unitType_sortOrder_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        nullable=False,
    )
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        String(191),
        ForeignKey("LibraryResourceAsset.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    unit_type: Mapped[str] = mapped_column("unitType", String(191), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    href: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(
        "mediaType", String(191), nullable=True
    )
    sort_order: Mapped[int] = mapped_column("sortOrder", Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_ms: Mapped[int | None] = mapped_column("startMs", Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column("endMs", Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(
        "durationMs", Integer, nullable=True
    )
    metadata_json: Mapped[str] = mapped_column("metadataJson", Text, nullable=False)
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


class ReaderResourceProgress(Base):
    __tablename__ = "ReaderResourceProgress"
    __table_args__ = (
        Index("ReaderResourceProgress_resourceId_idx", "resourceId"),
        Index(
            "ReaderResourceProgress_clientId_clientSequence_idx",
            "clientId",
            "clientSequence",
        ),
        UniqueConstraint(
            "userId",
            "resourceId",
            name="ReaderResourceProgress_userId_resourceId_key",
        ),
        Index(
            "ReaderResourceProgress_userId_updatedAt_resourceId_idx",
            "userId",
            "updatedAt",
            "resourceId",
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
    reader_type: Mapped[str] = mapped_column("readerType", String(191), nullable=False)
    position: Mapped[str] = mapped_column(
        Text, nullable=False, default="0", server_default="0"
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    extra: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        "schemaVersion", Integer, nullable=False, default=3, server_default="3"
    )
    location_type: Mapped[str | None] = mapped_column(
        "locationType", String(191), nullable=True
    )
    location_json: Mapped[str | None] = mapped_column(
        "locationJson", Text, nullable=True
    )
    mutation_id: Mapped[str | None] = mapped_column(
        "mutationId", String(191), nullable=True
    )
    client_id: Mapped[str | None] = mapped_column(
        "clientId", String(191), nullable=True
    )
    client_sequence: Mapped[int | None] = mapped_column(
        "clientSequence", Integer, nullable=True
    )
    progressed_at: Mapped[datetime] = mapped_column(
        "progressedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    source_protocol: Mapped[str] = mapped_column(
        "sourceProtocol",
        String(32),
        nullable=False,
        default="SHUKU_WEB",
        server_default="SHUKU_WEB",
    )
    source_device_name: Mapped[str | None] = mapped_column(
        "sourceDeviceName", String(191), nullable=True
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
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ReaderProgressMutation(Base):
    """Bounded idempotency receipt for an exact resource progress mutation."""

    __tablename__ = "ReaderProgressMutation"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "resourceId",
            "mutationId",
            name="ReaderProgressMutation_userId_resourceId_mutationId_key",
        ),
        Index(
            "ReaderProgressMutation_userId_resourceId_revision_idx",
            "userId",
            "resourceId",
            "revision",
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
    mutation_id: Mapped[str] = mapped_column("mutationId", String(36), nullable=False)
    client_id: Mapped[str] = mapped_column("clientId", String(256), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_json: Mapped[str] = mapped_column("locatorJson", Text, nullable=False)
    display_percent: Mapped[float] = mapped_column(
        "displayPercent", Float, nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        "capturedAt", TimestampMilliseconds(), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        "receivedAt", TimestampMilliseconds(), nullable=False
    )


class BookDetailPreference(Base):
    __tablename__ = "BookDetailPreference"
    __table_args__ = (
        Index("BookDetailPreference_user_book_key", "userId", "bookId", unique=True),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    book_id: Mapped[str] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    selected_tab: Mapped[str] = mapped_column(
        "selectedTab", String(191), nullable=False
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


class ExternalMetadataCache(Base):
    __tablename__ = "ExternalMetadataCache"
    __table_args__ = (
        Index("ExternalMetadataCache_provider_expiresAt_idx", "provider", "expiresAt"),
        Index(
            "ExternalMetadataCache_provider_queryKey_key",
            "provider",
            "queryKey",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    provider: Mapped[str] = mapped_column(String(191), nullable=False)
    query_key: Mapped[str] = mapped_column("queryKey", Text, nullable=False)
    raw_json: Mapped[str] = mapped_column("rawJson", Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        "expiresAt", TimestampMilliseconds(), nullable=True
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


__all__ = [
    "BookDetailPreference",
    "ExternalMetadataCache",
    "Library",
    "LibraryBookFacet",
    "LibraryFacet",
    "LibraryOperation",
    "LibraryReadableResourceFacet",
    "ReadableResourceNavigationUnit",
    "ReaderProgressMutation",
    "ReaderResourceProgress",
]

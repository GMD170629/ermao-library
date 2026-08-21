"""Fresh-baseline ORM tables for the SourceNode / Book / Resource / Asset model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    column,
    func,
    or_,
)
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default

_PATH_KEY_LENGTH = 67  # "v1:" + 64-char lowercase SHA-256 hex digest


class LibrarySourceNode(Base):
    __tablename__ = "LibrarySourceNode"
    __table_args__ = (
        CheckConstraint(
            column("physicalKind").in_(
                ("REGULAR_FILE", "DIRECTORY", "SYMLINK", "OTHER")
            ),
            name="LibrarySourceNode_physicalKind_check",
        ),
        CheckConstraint(
            and_(
                func.length(column("pathKey")) == _PATH_KEY_LENGTH,
                func.substr(column("pathKey"), 1, 3) == "v1:",
            ),
            name="LibrarySourceNode_pathKey_format_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("parentId").is_(None),
                    column("parentPhysicalKind").is_(None),
                ),
                and_(
                    column("parentId").is_not(None),
                    column("parentPhysicalKind") == "DIRECTORY",
                ),
            ),
            name="LibrarySourceNode_parent_pair_check",
        ),
        CheckConstraint(
            or_(
                column("parentId").is_(None),
                column("parentId") != column("id"),
            ),
            name="LibrarySourceNode_no_self_parent_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("physicalKind") == "DIRECTORY",
                    column("observedSizeBytes").is_(None),
                ),
                and_(
                    column("physicalKind") != "DIRECTORY",
                    column("observedSizeBytes").is_not(None),
                    column("observedSizeBytes") >= 0,
                ),
            ),
            name="LibrarySourceNode_observedSizeBytes_check",
        ),
        UniqueConstraint(
            "libraryId",
            "pathKey",
            name="LibrarySourceNode_libraryId_pathKey_key",
        ),
        UniqueConstraint(
            "id",
            "libraryId",
            name="LibrarySourceNode_id_libraryId_key",
        ),
        UniqueConstraint(
            "id",
            "physicalKind",
            name="LibrarySourceNode_id_physicalKind_key",
        ),
        ForeignKeyConstraint(
            ["parentId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibrarySourceNode_parent_library",
        ),
        ForeignKeyConstraint(
            ["parentId", "parentPhysicalKind"],
            ["LibrarySourceNode.id", "LibrarySourceNode.physicalKind"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibrarySourceNode_parent_directory",
        ),
        Index("LibrarySourceNode_libraryId_parentId_idx", "libraryId", "parentId"),
        Index("LibrarySourceNode_libraryId_name_idx", "libraryId", "name"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column("parentId", String(191), nullable=True)
    # Shadow: pairs with parentId; must be DIRECTORY when parent is set.
    parent_physical_kind: Mapped[str | None] = mapped_column(
        "parentPhysicalKind", String(32), nullable=True
    )
    relative_path: Mapped[str] = mapped_column("relativePath", Text, nullable=False)
    path_key: Mapped[str] = mapped_column("pathKey", String(_PATH_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    physical_kind: Mapped[str] = mapped_column("physicalKind", String(32), nullable=False)
    observed_size_bytes: Mapped[int | None] = mapped_column(
        "observedSizeBytes", BigInteger, nullable=True
    )
    observed_mtime_ns: Mapped[int] = mapped_column(
        "observedMtimeNs", BigInteger, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        "observedAt", TimestampMilliseconds(), nullable=False
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

    books: Mapped[list["LibraryBook"]] = relationship(
        back_populates="source_node",
        foreign_keys="LibraryBook.source_node_id",
        primaryjoin=(
            "and_(LibrarySourceNode.id==LibraryBook.source_node_id,"
            "LibrarySourceNode.library_id==LibraryBook.library_id)"
        ),
        passive_deletes=True,
    )
    anchored_resources: Mapped[list["LibraryReadableResource"]] = relationship(
        back_populates="source_node",
        foreign_keys="LibraryReadableResource.source_node_id",
        primaryjoin=(
            "and_(LibrarySourceNode.id==LibraryReadableResource.source_node_id,"
            "LibrarySourceNode.library_id==LibraryReadableResource.library_id)"
        ),
        passive_deletes=True,
    )
    resource_assets: Mapped[list["LibraryResourceAsset"]] = relationship(
        back_populates="source_node",
        foreign_keys="LibraryResourceAsset.source_node_id",
        primaryjoin=(
            "and_(LibrarySourceNode.id==LibraryResourceAsset.source_node_id,"
            "LibrarySourceNode.library_id==LibraryResourceAsset.library_id)"
        ),
        passive_deletes=True,
    )


class LibrarySourceNodeMetadata(Base):
    __tablename__ = "LibrarySourceNodeMetadata"

    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId",
        String(191),
        ForeignKey("LibrarySourceNode.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
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


class LibrarySourceNodeInterpretation(Base):
    __tablename__ = "LibrarySourceNodeInterpretation"
    __table_args__ = (
        CheckConstraint(
            column("result").in_(("NODE_ONLY", "RESOURCE")),
            name="LibrarySourceNodeInterpretation_result_check",
        ),
        CheckConstraint(
            column("source").in_(("AUTO", "USER")),
            name="LibrarySourceNodeInterpretation_source_check",
        ),
    )

    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId",
        String(191),
        ForeignKey("LibrarySourceNode.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_id: Mapped[str | None] = mapped_column("adapterId", String(191), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(
        "adapterVersion", String(64), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column("reasonCode", String(64), nullable=True)
    # Newline-separated relative paths from directory probe (not generic metadata JSON).
    sample_relative_paths: Mapped[str | None] = mapped_column(
        "sampleRelativePaths", Text, nullable=True
    )
    sample_count: Mapped[int | None] = mapped_column("sampleCount", Integer, nullable=True)
    max_entries_visited: Mapped[int | None] = mapped_column(
        "maxEntriesVisited", Integer, nullable=True
    )
    max_depth: Mapped[int | None] = mapped_column("maxDepth", Integer, nullable=True)
    time_budget_ms: Mapped[int | None] = mapped_column(
        "timeBudgetMs", Integer, nullable=True
    )
    termination_reason: Mapped[str | None] = mapped_column(
        "terminationReason", String(64), nullable=True
    )
    recognized_at: Mapped[datetime | None] = mapped_column(
        "recognizedAt", TimestampMilliseconds(), nullable=True
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


class LibraryBook(Base):
    __tablename__ = "LibraryBook"
    __table_args__ = (
        UniqueConstraint("sourceNodeId", name="LibraryBook_sourceNodeId_key"),
        UniqueConstraint(
            "id",
            "libraryId",
            name="LibraryBook_id_libraryId_key",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryBook_sourceNode_library",
        ),
        Index("LibraryBook_libraryId_idx", "libraryId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
    )
    visibility_state: Mapped[str] = mapped_column(
        "visibilityState",
        String(32),
        nullable=False,
        default="VISIBLE",
        server_default="VISIBLE",
    )
    curation_state: Mapped[str] = mapped_column(
        "curationState",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
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
    source_node: Mapped[LibrarySourceNode] = relationship(
        back_populates="books",
        foreign_keys=[source_node_id, library_id],
        primaryjoin=(
            "and_(LibraryBook.source_node_id==LibrarySourceNode.id,"
            "LibraryBook.library_id==LibrarySourceNode.library_id)"
        ),
    )
    resources: Mapped[list["LibraryReadableResource"]] = relationship(
        back_populates="book",
        foreign_keys="LibraryReadableResource.book_id",
        primaryjoin=(
            "and_(LibraryBook.id==LibraryReadableResource.book_id,"
            "LibraryBook.library_id==LibraryReadableResource.library_id)"
        ),
        passive_deletes=True,
    )


class LibraryBookMetadata(Base):
    __tablename__ = "LibraryBookMetadata"

    book_id: Mapped[str] = mapped_column(
        "bookId",
        String(191),
        ForeignKey("LibraryBook.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column("normalizedTitle", Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_author: Mapped[str | None] = mapped_column(
        "normalizedAuthor", Text, nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_name: Mapped[str | None] = mapped_column("seriesName", Text, nullable=True)
    series_index: Mapped[float | None] = mapped_column("seriesIndex", Float, nullable=True)
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    metadata_quality: Mapped[int] = mapped_column(
        "metadataQuality", Integer, nullable=False, default=0, server_default="0"
    )
    publication_status: Mapped[str] = mapped_column(
        "publicationStatus",
        String(32),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )
    tracking_status: Mapped[str] = mapped_column(
        "trackingStatus",
        String(32),
        nullable=False,
        default="NOT_TRACKING",
        server_default="NOT_TRACKING",
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


class LibraryReadableResource(Base):
    __tablename__ = "LibraryReadableResource"
    __table_args__ = (
        CheckConstraint(
            column("enablementState").in_(("ENABLED", "DISABLED")),
            name="LibraryReadableResource_enablementState_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="LibraryReadableResource_importState_check",
        ),
        UniqueConstraint("sourceNodeId", name="LibraryReadableResource_sourceNodeId_key"),
        UniqueConstraint(
            "id",
            "libraryId",
            name="LibraryReadableResource_id_libraryId_key",
        ),
        ForeignKeyConstraint(
            ["bookId", "libraryId"],
            ["LibraryBook.id", "LibraryBook.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryReadableResource_book_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryReadableResource_sourceNode_library",
        ),
        Index("LibraryReadableResource_bookId_idx", "bookId"),
        Index("LibraryReadableResource_libraryId_idx", "libraryId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    book_id: Mapped[str] = mapped_column("bookId", String(191), nullable=False)
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
    )
    adapter_id: Mapped[str] = mapped_column("adapterId", String(191), nullable=False)
    adapter_version: Mapped[str] = mapped_column(
        "adapterVersion", String(64), nullable=False
    )
    media_kind: Mapped[str] = mapped_column("mediaKind", String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    enablement_state: Mapped[str] = mapped_column(
        "enablementState",
        String(32),
        nullable=False,
        default="ENABLED",
        server_default="ENABLED",
    )
    import_state: Mapped[str] = mapped_column(
        "importState",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
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
    book: Mapped[LibraryBook] = relationship(
        back_populates="resources",
        foreign_keys=[book_id, library_id],
        primaryjoin=(
            "and_(LibraryReadableResource.book_id==LibraryBook.id,"
            "LibraryReadableResource.library_id==LibraryBook.library_id)"
        ),
    )
    source_node: Mapped[LibrarySourceNode] = relationship(
        back_populates="anchored_resources",
        foreign_keys=[source_node_id, library_id],
        primaryjoin=(
            "and_(LibraryReadableResource.source_node_id==LibrarySourceNode.id,"
            "LibraryReadableResource.library_id==LibrarySourceNode.library_id)"
        ),
        overlaps="book",
    )
    assets: Mapped[list["LibraryResourceAsset"]] = relationship(
        back_populates="resource",
        foreign_keys="LibraryResourceAsset.resource_id",
        primaryjoin=(
            "and_(LibraryReadableResource.id==LibraryResourceAsset.resource_id,"
            "LibraryReadableResource.library_id==LibraryResourceAsset.library_id)"
        ),
        passive_deletes=True,
    )


class LibraryReadableResourceMetadata(Base):
    __tablename__ = "LibraryReadableResourceMetadata"

    resource_id: Mapped[str] = mapped_column(
        "resourceId",
        String(191),
        ForeignKey(
            "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
        ),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        "publishedAt", TimestampMilliseconds(), nullable=True
    )
    identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int | None] = mapped_column("pageCount", Integer, nullable=True)
    chapter_count: Mapped[int | None] = mapped_column(
        "chapterCount", Integer, nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column("durationMs", Integer, nullable=True)
    track_count: Mapped[int | None] = mapped_column("trackCount", Integer, nullable=True)
    narrator: Mapped[str | None] = mapped_column(Text, nullable=True)
    abridged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resource_index: Mapped[float | None] = mapped_column(
        "resourceIndex", Float, nullable=True
    )
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
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


class LibraryResourceAsset(Base):
    __tablename__ = "LibraryResourceAsset"
    __table_args__ = (
        CheckConstraint(
            column("role").in_(
                ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
            ),
            name="LibraryResourceAsset_role_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="LibraryResourceAsset_importState_check",
        ),
        CheckConstraint(
            column("sourceNodePhysicalKind") == "REGULAR_FILE",
            name="LibraryResourceAsset_sourceNodePhysicalKind_check",
        ),
        UniqueConstraint(
            "resourceId",
            "sourceNodeId",
            name="LibraryResourceAsset_resourceId_sourceNodeId_key",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_resource_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_sourceNode_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "sourceNodePhysicalKind"],
            ["LibrarySourceNode.id", "LibrarySourceNode.physicalKind"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_sourceNode_file",
        ),
        Index(
            "LibraryResourceAsset_resourceId_importState_idx",
            "resourceId",
            "importState",
        ),
        Index("LibraryResourceAsset_sourceNodeId_idx", "sourceNodeId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column("resourceId", String(191), nullable=False)
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
    )
    # Shadow: must remain REGULAR_FILE; composite FK enforces node kind.
    source_node_physical_kind: Mapped[str] = mapped_column(
        "sourceNodePhysicalKind",
        String(32),
        nullable=False,
        default="REGULAR_FILE",
        server_default="REGULAR_FILE",
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    import_state: Mapped[str] = mapped_column(
        "importState",
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    sequence_index: Mapped[int | None] = mapped_column(
        "sequenceIndex", Integer, nullable=True
    )
    sort_key: Mapped[str | None] = mapped_column("sortKey", Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(
        "failureReason", Text, nullable=True
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
    resource: Mapped[LibraryReadableResource] = relationship(
        back_populates="assets",
        foreign_keys=[resource_id, library_id],
        primaryjoin=(
            "and_(LibraryResourceAsset.resource_id==LibraryReadableResource.id,"
            "LibraryResourceAsset.library_id==LibraryReadableResource.library_id)"
        ),
    )
    source_node: Mapped[LibrarySourceNode] = relationship(
        back_populates="resource_assets",
        foreign_keys=[source_node_id, library_id],
        primaryjoin=(
            "and_(LibraryResourceAsset.source_node_id==LibrarySourceNode.id,"
            "LibraryResourceAsset.library_id==LibrarySourceNode.library_id)"
        ),
        overlaps="resource",
    )


class LibraryResourceAssetMetadata(Base):
    __tablename__ = "LibraryResourceAssetMetadata"

    asset_id: Mapped[str] = mapped_column(
        "assetId",
        String(191),
        ForeignKey("LibraryResourceAsset.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    mime_type: Mapped[str | None] = mapped_column("mimeType", String(191), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column("durationMs", Integer, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column("sampleRate", Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column("discNumber", Integer, nullable=True)
    track_number: Mapped[int | None] = mapped_column(
        "trackNumber", Integer, nullable=True
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
    "LibraryBook",
    "LibraryBookMetadata",
    "LibraryReadableResource",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "LibrarySourceNode",
    "LibrarySourceNodeInterpretation",
    "LibrarySourceNodeMetadata",
]

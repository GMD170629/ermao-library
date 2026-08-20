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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default


class Library(Base):
    __tablename__ = "Library"
    __table_args__ = (
        CheckConstraint(
            "organizationMode IN ('FLAT', 'VOLUMES', 'AUDIOBOOK')",
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


class LibraryWork(Base):
    __tablename__ = "LibraryWork"
    __table_args__ = (
        UniqueConstraint(
            "libraryId",
            "sourceKey",
            name="LibraryWork_libraryId_sourceKey_key",
        ),
        Index("LibraryWork_publicationStatus_idx", "publicationStatus"),
        Index("LibraryWork_trackingStatus_idx", "trackingStatus"),
        Index("LibraryWork_title_idx", "title"),
        Index("LibraryWork_normalizedTitle_idx", "normalizedTitle"),
        Index("LibraryWork_normalizedAuthor_idx", "normalizedAuthor"),
        Index("LibraryWork_seriesName_idx", "seriesName"),
        Index("LibraryWork_organizeStatus_idx", "organizeStatus"),
        Index("LibraryWork_hidden_idx", "hidden"),
        Index("LibraryWork_organized_idx", "organized"),
        Index("LibraryWork_libraryId_idx", "libraryId"),
        Index("LibraryWork_sourceKey_idx", "sourceKey"),
        Index("LibraryWork_createdAt_id_idx", "createdAt", "id"),
        Index("LibraryWork_hidden_createdAt_id_idx", "hidden", "createdAt", "id"),
        Index(
            "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx",
            "hidden",
            "normalizedTitle",
            "normalizedAuthor",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    origin: Mapped[str] = mapped_column(
        String(191), nullable=False, default="SCAN", server_default="SCAN"
    )
    source_key: Mapped[str | None] = mapped_column(
        "sourceKey", String(191), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(
        "normalizedTitle", Text, nullable=False
    )
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_author: Mapped[str | None] = mapped_column(
        "normalizedAuthor", Text, nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_status: Mapped[str] = mapped_column(
        "publicationStatus",
        String(191),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )
    tracking_status: Mapped[str] = mapped_column(
        "trackingStatus",
        String(191),
        nullable=False,
        default="NOT_TRACKING",
        server_default="NOT_TRACKING",
    )
    local_latest_volume: Mapped[float | None] = mapped_column(
        "localLatestVolume", Float, nullable=True
    )
    local_latest_chapter: Mapped[float | None] = mapped_column(
        "localLatestChapter", Float, nullable=True
    )
    local_latest_title: Mapped[str | None] = mapped_column(
        "localLatestTitle", Text, nullable=True
    )
    local_latest_at: Mapped[datetime | None] = mapped_column(
        "localLatestAt", TimestampMilliseconds(), nullable=True
    )
    tags: Mapped[str] = mapped_column(Text, nullable=False)
    series_name: Mapped[str | None] = mapped_column("seriesName", Text, nullable=True)
    series_index: Mapped[float | None] = mapped_column(
        "seriesIndex", Float, nullable=True
    )
    metadata_quality: Mapped[int] = mapped_column(
        "metadataQuality", Integer, nullable=False, default=0, server_default="0"
    )
    organize_status: Mapped[str] = mapped_column(
        "organizeStatus",
        String(191),
        nullable=False,
        default="REVIEWING",
        server_default="REVIEWING",
    )
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus",
        String(191),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    organized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
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


class LibraryVersion(Base):
    __tablename__ = "LibraryVersion"
    __table_args__ = (
        UniqueConstraint(
            "workId",
            "sourceKey",
            name="LibraryVersion_workId_sourceKey_key",
        ),
        Index("LibraryVersion_workId_idx", "workId"),
        Index("LibraryVersion_sourceKey_idx", "sourceKey"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column("sourceKey", String(191), nullable=False)
    source_name: Mapped[str | None] = mapped_column("sourceName", Text, nullable=True)
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus", String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    work: Mapped[LibraryWork] = relationship()
    volumes: Mapped[list[LibraryVolume]] = relationship(back_populates="version")
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


class LibraryVolume(Base):
    __tablename__ = "LibraryVolume"
    __table_args__ = (
        UniqueConstraint(
            "versionId",
            "resourceKey",
            name="LibraryVolume_versionId_resourceKey_key",
        ),
        Index("LibraryVolume_versionId_sortOrder_idx", "versionId", "sortOrder"),
        Index(
            "LibraryVolume_versionId_volumeIndex_idx",
            "versionId",
            "volumeIndex",
        ),
        Index(
            "LibraryVolume_versionId_hidden_idx",
            "versionId",
            "hidden",
        ),
        Index("LibraryVolume_format_idx", "format"),
        Index("LibraryVolume_identifier_idx", "identifier"),
        Index("LibraryVolume_isbn_idx", "isbn"),
        Index("LibraryVolume_resourceKey_idx", "resourceKey"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    version_id: Mapped[str] = mapped_column(
        "versionId",
        String(191),
        ForeignKey("LibraryVersion.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    version: Mapped[LibraryVersion] = relationship(back_populates="volumes")
    origin: Mapped[str] = mapped_column(
        String(191), nullable=False, default="SCAN", server_default="SCAN"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    volume_index: Mapped[float | None] = mapped_column(
        "volumeIndex", Float, nullable=True
    )
    sort_order: Mapped[int] = mapped_column(
        "sortOrder", Integer, nullable=False, default=0, server_default="0"
    )
    format: Mapped[str] = mapped_column(String(191), nullable=False)
    classification_source: Mapped[str] = mapped_column(
        "classificationSource",
        String(32),
        nullable=False,
        default="AUTO",
        server_default="AUTO",
    )
    classification_reason: Mapped[str] = mapped_column(
        "classificationReason",
        String(64),
        nullable=False,
        default="FORMAT_DEFAULT",
        server_default="FORMAT_DEFAULT",
    )
    suggested_media_kind: Mapped[str | None] = mapped_column(
        "suggestedMediaKind", String(32), nullable=True
    )
    resource_key: Mapped[str] = mapped_column(
        "resourceKey", String(191), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(191), nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        "publishedAt", TimestampMilliseconds(), nullable=True
    )
    identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(191), nullable=True)
    import_status: Mapped[str] = mapped_column(
        "importStatus",
        String(191),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    import_error: Mapped[str | None] = mapped_column("importError", Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(
        "sizeBytes", Integer, nullable=False, default=0, server_default="0"
    )
    page_count: Mapped[int | None] = mapped_column("pageCount", Integer, nullable=True)
    chapter_count: Mapped[int | None] = mapped_column(
        "chapterCount", Integer, nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(
        "durationMs", Integer, nullable=True
    )
    track_count: Mapped[int | None] = mapped_column(
        "trackCount", Integer, nullable=True
    )
    narrator: Mapped[str | None] = mapped_column(Text, nullable=True)
    abridged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
    cover_status: Mapped[str] = mapped_column(
        "coverStatus",
        String(191),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
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


class LibraryFile(Base):
    __tablename__ = "LibraryFile"
    __table_args__ = (
        Index("LibraryFile_path_key", "path", unique=True),
        Index("LibraryFile_filePathHash_key", "filePathHash", unique=True),
        Index("LibraryFile_volumeId_sortOrder_idx", "volumeId", "sortOrder"),
        Index("LibraryFile_sizeBytes_mtimeMs_idx", "sizeBytes", "mtimeMs"),
        Index("LibraryFile_pathKey_idx", "pathKey"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str | None] = mapped_column("pathKey", String(64), nullable=True)
    file_path_hash: Mapped[str | None] = mapped_column(
        "filePathHash", String(191), nullable=True
    )
    mtime_ms: Mapped[int] = mapped_column(
        "mtimeMs", Integer, nullable=False, default=0, server_default="0"
    )
    kind: Mapped[str] = mapped_column(String(191), nullable=False)
    mime_type: Mapped[str] = mapped_column("mimeType", String(191), nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        "sizeBytes", Integer, nullable=False, default=0, server_default="0"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        "durationMs", Integer, nullable=True
    )
    codec: Mapped[str | None] = mapped_column(String(191), nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(
        "sampleRate", Integer, nullable=True
    )
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column(
        "discNumber", Integer, nullable=True
    )
    track_number: Mapped[int | None] = mapped_column(
        "trackNumber", Integer, nullable=True
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
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class LibraryFacet(Base):
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


class LibraryWorkFacet(Base):
    __tablename__ = "LibraryWorkFacet"
    __table_args__ = (Index("LibraryWorkFacet_workId_idx", "workId"),)

    facet_id: Mapped[str] = mapped_column(
        "facetId",
        String(191),
        ForeignKey("LibraryFacet.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
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


class LibraryVolumeFacet(Base):
    __tablename__ = "LibraryVolumeFacet"
    __table_args__ = (Index("LibraryVolumeFacet_volumeId_idx", "volumeId"),)

    facet_id: Mapped[str] = mapped_column(
        "facetId",
        String(191),
        ForeignKey("LibraryFacet.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
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


class LibraryReadingUnit(Base):
    __tablename__ = "LibraryReadingUnit"
    __table_args__ = (
        Index("LibraryReadingUnit_volumeId_sortOrder_idx", "volumeId", "sortOrder"),
        Index("LibraryReadingUnit_fileId_sortOrder_idx", "fileId", "sortOrder"),
        Index(
            "LibraryReadingUnit_volumeId_unitType_sortOrder_key",
            "volumeId",
            "unitType",
            "sortOrder",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[str | None] = mapped_column(
        "fileId",
        String(191),
        ForeignKey("LibraryFile.id", ondelete="SET NULL", onupdate="CASCADE"),
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


class LibraryMetadata(Base):
    __tablename__ = "LibraryMetadata"
    __table_args__ = (Index("LibraryMetadata_volumeId_idx", "volumeId"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(191), nullable=False)
    raw_json: Mapped[str] = mapped_column("rawJson", Text, nullable=False)
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


class LibraryReadingProgress(Base):
    __tablename__ = "LibraryReadingProgress"
    __table_args__ = (
        Index("LibraryReadingProgress_volumeId_idx", "volumeId"),
        Index(
            "LibraryReadingProgress_clientId_clientSequence_idx",
            "clientId",
            "clientSequence",
        ),
        Index(
            "LibraryReadingProgress_userId_volumeId_key",
            "userId",
            "volumeId",
            unique=True,
        ),
        Index(
            "LibraryReadingProgress_userId_updatedAt_volumeId_idx",
            "userId",
            "updatedAt",
            "volumeId",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
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
    """Bounded idempotency receipt for an exact Reader v4 progress mutation."""

    __tablename__ = "ReaderProgressMutation"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "volumeId",
            "mutationId",
            name="ReaderProgressMutation_userId_volumeId_mutationId_key",
        ),
        Index(
            "ReaderProgressMutation_userId_volumeId_revision_idx",
            "userId",
            "volumeId",
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
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
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


class WorkDetailPreference(Base):
    __tablename__ = "WorkDetailPreference"
    __table_args__ = (
        Index("WorkDetailPreference_user_work_key", "userId", "workId", unique=True),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
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

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


class LibraryWork(Base):
    __tablename__ = "LibraryWork"
    __table_args__ = (
        Index("LibraryWork_workType_idx", "workType"),
        Index("LibraryWork_publicationStatus_idx", "publicationStatus"),
        Index("LibraryWork_trackingStatus_idx", "trackingStatus"),
        Index("LibraryWork_title_idx", "title"),
        Index("LibraryWork_normalizedTitle_idx", "normalizedTitle"),
        Index("LibraryWork_normalizedAuthor_idx", "normalizedAuthor"),
        Index("LibraryWork_seriesName_idx", "seriesName"),
        Index("LibraryWork_publishedYear_idx", "publishedYear"),
        Index("LibraryWork_organizeStatus_idx", "organizeStatus"),
        Index("LibraryWork_hidden_idx", "hidden"),
        Index("LibraryWork_organized_idx", "organized"),
        Index("LibraryWork_monitorFolderId_idx", "monitorFolderId"),
        Index("LibraryWork_mergeKey_idx", "mergeKey"),
        Index("LibraryWork_createdAt_id_idx", "createdAt", "id"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    monitor_folder_id: Mapped[str | None] = mapped_column(
        "monitorFolderId",
        String(191),
        ForeignKey("MonitorFolder.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    origin: Mapped[str] = mapped_column(
        String(191), nullable=False, default="MANUAL", server_default="MANUAL"
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
    work_type: Mapped[str] = mapped_column("workType", String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(191), nullable=False, default="UNREAD", server_default="UNREAD"
    )
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
    published_year: Mapped[int | None] = mapped_column(
        "publishedYear", Integer, nullable=True
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
    primary_edition_id: Mapped[str | None] = mapped_column(
        "primaryEditionId", String(191), nullable=True
    )
    merge_key: Mapped[str | None] = mapped_column("mergeKey", Text, nullable=True)
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


class LibraryEdition(Base):
    __tablename__ = "LibraryEdition"
    __table_args__ = (
        Index("LibraryEdition_workId_mediaKind_idx", "workId", "mediaKind"),
        Index(
            "LibraryEdition_workId_mediaKind_primary_key",
            "workId",
            "mediaKind",
            unique=True,
            sqlite_where=column("primary", Boolean).is_(True)
            & column("hidden", Boolean).is_(False),
        ),
        Index("LibraryEdition_workId_primary_idx", "workId", "primary"),
        Index("LibraryEdition_format_idx", "format"),
        Index("LibraryEdition_identifier_idx", "identifier"),
        Index("LibraryEdition_isbn_idx", "isbn"),
        Index("LibraryEdition_sourceGroupKey_idx", "sourceGroupKey"),
        Index("LibraryEdition_monitorFolderId_idx", "monitorFolderId"),
        Index(
            "LibraryEdition_workId_versionKey_key", "workId", "versionKey", unique=True
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    monitor_folder_id: Mapped[str | None] = mapped_column(
        "monitorFolderId",
        String(191),
        ForeignKey("MonitorFolder.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    origin: Mapped[str] = mapped_column(
        String(191), nullable=False, default="MANUAL", server_default="MANUAL"
    )
    media_kind: Mapped[str] = mapped_column(
        "mediaKind",
        String(191),
        nullable=False,
        default="EBOOK",
        server_default="EBOOK",
    )
    format: Mapped[str] = mapped_column(String(191), nullable=False)
    version_name: Mapped[str] = mapped_column("versionName", Text, nullable=False)
    version_key: Mapped[str] = mapped_column("versionKey", String(191), nullable=False)
    source_group_key: Mapped[str | None] = mapped_column(
        "sourceGroupKey", Text, nullable=True
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
    is_primary: Mapped[bool] = mapped_column(
        "primary", Boolean, nullable=False, default=False, server_default="0"
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


class LibraryVolume(Base):
    __tablename__ = "LibraryVolume"
    __table_args__ = (
        Index("LibraryVolume_editionId_sortOrder_idx", "editionId", "sortOrder"),
        Index("LibraryVolume_editionId_volumeIndex_idx", "editionId", "volumeIndex"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    volume_index: Mapped[float | None] = mapped_column(
        "volumeIndex", Float, nullable=True
    )
    sort_order: Mapped[int] = mapped_column(
        "sortOrder", Integer, nullable=False, default=0, server_default="0"
    )
    page_count: Mapped[int | None] = mapped_column("pageCount", Integer, nullable=True)
    chapter_count: Mapped[int | None] = mapped_column(
        "chapterCount", Integer, nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(
        "durationMs", Integer, nullable=True
    )
    cover_path: Mapped[str | None] = mapped_column("coverPath", Text, nullable=True)
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
        Index("LibraryFile_fullHash_key", "fullHash", unique=True),
        Index("LibraryFile_editionId_sortOrder_idx", "editionId", "sortOrder"),
        Index("LibraryFile_volumeId_sortOrder_idx", "volumeId", "sortOrder"),
        Index("LibraryFile_fingerprint_idx", "fingerprint"),
        Index("LibraryFile_fullHash_idx", "fullHash"),
        Index("LibraryFile_sizeBytes_mtimeMs_idx", "sizeBytes", "mtimeMs"),
        Index("LibraryFile_pathKey_idx", "pathKey"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[str | None] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str | None] = mapped_column("pathKey", String(64), nullable=True)
    file_path_hash: Mapped[str | None] = mapped_column(
        "filePathHash", String(191), nullable=True
    )
    fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_hash: Mapped[str | None] = mapped_column(
        "fullHash", String(191), nullable=True
    )
    hash_status: Mapped[str] = mapped_column(
        "hashStatus",
        String(191),
        nullable=False,
        default="FAILED",
        server_default="FAILED",
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


class LibraryEditionFacet(Base):
    __tablename__ = "LibraryEditionFacet"
    __table_args__ = (Index("LibraryEditionFacet_editionId_idx", "editionId"),)

    facet_id: Mapped[str] = mapped_column(
        "facetId",
        String(191),
        ForeignKey("LibraryFacet.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
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
        Index("LibraryReadingUnit_editionId_sortOrder_idx", "editionId", "sortOrder"),
        Index("LibraryReadingUnit_editionId_unitType_idx", "editionId", "unitType"),
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
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[str | None] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
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
    __table_args__ = (Index("LibraryMetadata_editionId_idx", "editionId"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
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
        Index("LibraryReadingProgress_workId_idx", "workId"),
        Index("LibraryReadingProgress_editionId_idx", "editionId"),
        Index("LibraryReadingProgress_volumeId_idx", "volumeId"),
        Index(
            "LibraryReadingProgress_clientId_clientSequence_idx",
            "clientId",
            "clientSequence",
        ),
        Index(
            "LibraryReadingProgress_userId_editionId_volumeId_key",
            "userId",
            "editionId",
            "volumeId",
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
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    edition_id: Mapped[str] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[str | None] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
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
        "schemaVersion", Integer, nullable=False, default=1, server_default="1"
    )
    location_type: Mapped[str | None] = mapped_column(
        "locationType", String(191), nullable=True
    )
    location_json: Mapped[str | None] = mapped_column(
        "locationJson", Text, nullable=True
    )
    content_fingerprint: Mapped[str | None] = mapped_column(
        "contentFingerprint", String(191), nullable=True
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


class LibraryConsumptionState(Base):
    __tablename__ = "LibraryConsumptionState"
    __table_args__ = (
        Index("LibraryConsumptionState_workId_idx", "workId"),
        Index(
            "LibraryConsumptionState_user_work_media_key",
            "userId",
            "workId",
            "mediaKind",
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
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    media_kind: Mapped[str] = mapped_column("mediaKind", String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(191), nullable=False, default="UNREAD", server_default="UNREAD"
    )
    last_edition_id: Mapped[str | None] = mapped_column(
        "lastEditionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    last_volume_id: Mapped[str | None] = mapped_column(
        "lastVolumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    last_unit_id: Mapped[str | None] = mapped_column(
        "lastUnitId",
        String(191),
        ForeignKey("LibraryReadingUnit.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
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

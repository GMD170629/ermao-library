"""Target ADR 0018 ImportRun / candidate / ImportTask ORM tables.

Isolated from the legacy ImportTask / ImportScanJob pipeline. Not wired into
workers or scanners in phase 1B.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default

_NONTERMINAL_RUN_STATES = ("PENDING", "RUNNING")


class LibraryImportRun(Base):
    __tablename__ = "LibraryImportRun"
    __table_args__ = (
        CheckConstraint(
            "\"kind\" IN ('INITIAL', 'RETRY', 'REIMPORT', 'RECOVERY')",
            name="LibraryImportRun_kind_check",
        ),
        CheckConstraint(
            "\"state\" IN ("
            "'PENDING', 'RUNNING', 'COMPLETED', "
            "'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED')",
            name="LibraryImportRun_state_check",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportRun_sourceNode_library",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            use_alter=True,
            name="fk_LibraryImportRun_resource_library",
        ),
        Index("LibraryImportRun_libraryId_state_idx", "libraryId", "state"),
        Index("LibraryImportRun_sourceNodeId_idx", "sourceNodeId"),
        Index(
            "LibraryImportRun_nonterminal_resource_key",
            "resourceId",
            unique=True,
            sqlite_where=and_(
                column("resourceId").is_not(None),
                column("state", String).in_(_NONTERMINAL_RUN_STATES),
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
    )
    resource_id: Mapped[str | None] = mapped_column(
        "resourceId", String(191), nullable=True
    )
    adapter_id: Mapped[str | None] = mapped_column("adapterId", String(191), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(
        "adapterVersion", String(64), nullable=True
    )
    error_summary: Mapped[str | None] = mapped_column(
        "errorSummary", Text, nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        "publishedAt", TimestampMilliseconds(), nullable=True
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


class ResourceCandidate(Base):
    """Temporary Resource-shaped row owned by one ImportRun; not a stable result."""

    __tablename__ = "ResourceCandidate"
    __table_args__ = (
        CheckConstraint(
            "\"enablementState\" IN ('ENABLED', 'DISABLED')",
            name="ResourceCandidate_enablementState_check",
        ),
        CheckConstraint(
            "\"importState\" IN ('PENDING', 'READY', 'FAILED')",
            name="ResourceCandidate_importState_check",
        ),
        UniqueConstraint("importRunId", name="ResourceCandidate_importRunId_key"),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_ResourceCandidate_sourceNode_library",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    import_run_id: Mapped[str] = mapped_column(
        "importRunId",
        String(191),
        ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    book_id: Mapped[str | None] = mapped_column("bookId", String(191), nullable=True)
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
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AssetCandidate(Base):
    """Temporary Asset-shaped row owned by one ImportRun; not a stable result."""

    __tablename__ = "AssetCandidate"
    __table_args__ = (
        CheckConstraint(
            "\"role\" IN "
            "('PRIMARY', 'TRACK', 'PAGE', 'SIDECAR', 'SUPPLEMENT')",
            name="AssetCandidate_role_check",
        ),
        CheckConstraint(
            "\"importState\" IN ('PENDING', 'READY', 'FAILED')",
            name="AssetCandidate_importState_check",
        ),
        UniqueConstraint(
            "importRunId",
            "sourceNodeId",
            name="AssetCandidate_importRunId_sourceNodeId_key",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_AssetCandidate_sourceNode_library",
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    import_run_id: Mapped[str] = mapped_column(
        "importRunId",
        String(191),
        ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
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


class LibraryImportTask(Base):
    """Per-file read task for readable-resource import (not legacy ImportTask)."""

    __tablename__ = "LibraryImportTask"
    __table_args__ = (
        CheckConstraint(
            "\"state\" IN "
            "('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="LibraryImportTask_state_check",
        ),
        CheckConstraint(
            "\"role\" IN "
            "('PRIMARY', 'TRACK', 'PAGE', 'SIDECAR', 'SUPPLEMENT')",
            name="LibraryImportTask_role_check",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_resource_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_sourceNode_library",
        ),
        Index(
            "LibraryImportTask_run_owned_key",
            "ownerImportRunId",
            "sourceNodeId",
            "role",
            unique=True,
            sqlite_where=column("ownerImportRunId").is_not(None),
        ),
        Index(
            "LibraryImportTask_incremental_key",
            "resourceId",
            "sourceNodeId",
            unique=True,
            sqlite_where=column("ownerImportRunId").is_(None),
        ),
        Index("LibraryImportTask_state_idx", "state"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="QUEUED",
        server_default="QUEUED",
    )
    resource_id: Mapped[str] = mapped_column("resourceId", String(191), nullable=False)
    source_node_id: Mapped[str] = mapped_column(
        "sourceNodeId", String(191), nullable=False
    )
    owner_import_run_id: Mapped[str | None] = mapped_column(
        "ownerImportRunId",
        String(191),
        ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        "attemptCount", Integer, nullable=False, default=0, server_default="0"
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


__all__ = [
    "AssetCandidate",
    "LibraryImportRun",
    "LibraryImportTask",
    "ResourceCandidate",
]

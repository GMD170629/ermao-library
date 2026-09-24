"""Fresh-baseline ORM table for the single-consumer ContinueImport task."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    and_,
    column,
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default

if TYPE_CHECKING:
    from app.models import LibraryReadableResource, LibrarySourceNode


class LibraryImportScanGap(Base):
    """Durable incomplete scan ranges that gate dependent import work.

    Stored outside the task row so cleanup, replacement or deletion of a scan
    task cannot silently release a directory resource whose member list was
    never fully enumerated. A fully completed scan covering a range removes it.
    """

    __tablename__ = "LibraryImportScanGap"

    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)


class LibraryImportTask(Base):
    """Single-consumer ContinueImport task."""

    __tablename__ = "LibraryImportTask"
    __table_args__ = (
        CheckConstraint(
            column("kind").in_(
                (
                    "SCAN_LIBRARY",
                    "CONTINUE_SOURCE",
                    "IMPORT_ASSET",
                    "IMPORT_RESOURCE",
                    "IDENTIFY_BOOK",
                    "IMPORT_BOOK",
                )
            ),
            name="LibraryImportTask_kind_check",
        ),
        CheckConstraint(
            column("state").in_(("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")),
            name="LibraryImportTask_state_check",
        ),
        CheckConstraint(
            column("missingEntryPolicy").in_(("PRESERVE", "PRUNE_MISSING")),
            name="LibraryImportTask_missingEntryPolicy_check",
        ),
        CheckConstraint(
            or_(
                column("role").is_(None),
                column("role").in_(
                    ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
                ),
            ),
            name="LibraryImportTask_role_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("kind") == "SCAN_LIBRARY",
                    column("sourceNodeId").is_(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind").in_(("CONTINUE_SOURCE", "IDENTIFY_BOOK")),
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind") == "IMPORT_RESOURCE",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_not(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind") == "IMPORT_ASSET",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_not(None),
                    column("role").is_not(None),
                ),
                and_(
                    column("kind") == "IMPORT_BOOK",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                    column("bookId").is_not(None),
                    column("bookWork").is_not(None),
                ),
            ),
            name="LibraryImportTask_kind_shape_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("kind") == "IMPORT_BOOK",
                    column("phase").is_not(None),
                    column("phase").in_(("SCAN", "RESOURCES", "IDENTIFY", "FINALIZE")),
                ),
                and_(
                    column("kind") != "IMPORT_BOOK",
                    column("bookId").is_(None),
                    column("phase").is_(None),
                ),
            ),
            name="LibraryImportTask_book_scope_check",
        ),
        CheckConstraint(
            and_(
                column("requestVersion") >= 0,
                column("retryCount") >= 0,
            ),
            name="LibraryImportTask_book_counters_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("kind") == "IMPORT_RESOURCE",
                    column("resourceAnchorNodeId").is_not(None),
                    column("resourceAnchorNodeId") == column("sourceNodeId"),
                ),
                and_(
                    column("kind") != "IMPORT_RESOURCE",
                    column("resourceAnchorNodeId").is_(None),
                ),
            ),
            name="LibraryImportTask_resource_anchor_check",
        ),
        ForeignKeyConstraint(
            ["resourceId", "resourceAnchorNodeId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.sourceNodeId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_resource_anchor",
        ),
        Index(
            "LibraryImportTask_resource_anchor_idx",
            "resourceId",
            "resourceAnchorNodeId",
        ),
        Index(
            "LibraryImportTask_import_resource_key",
            "resourceId",
            unique=True,
            sqlite_where=column("kind") == "IMPORT_RESOURCE",
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
        ForeignKeyConstraint(
            ["bookId", "libraryId"],
            ["LibraryBook.id", "LibraryBook.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_book_library",
        ),
        Index("LibraryImportTask_bookId_libraryId_idx", "bookId", "libraryId"),
        Index(
            "LibraryImportTask_book_runnable_idx",
            "state",
            "createdAt",
            "id",
            sqlite_where=and_(
                column("kind") == "IMPORT_BOOK",
                column("state") == "QUEUED",
            ),
        ),
        Index(
            "LibraryImportTask_import_asset_key",
            "resourceId",
            "sourceNodeId",
            unique=True,
            sqlite_where=column("kind") == "IMPORT_ASSET",
        ),
        Index(
            "LibraryImportTask_book_active_key",
            "sourceNodeId",
            unique=True,
            sqlite_where=and_(
                column("kind") == "IDENTIFY_BOOK",
                column("state").in_(("QUEUED", "RUNNING")),
            ),
        ),
        Index("LibraryImportTask_queued_createdAt_idx", "state", "createdAt"),
        Index("LibraryImportTask_sourceNodeId_idx", "sourceNodeId"),
        Index(
            "LibraryImportTask_sourceNodeId_libraryId_idx",
            "sourceNodeId",
            "libraryId",
        ),
        Index(
            "LibraryImportTask_resourceId_libraryId_idx",
            "resourceId",
            "libraryId",
        ),
        Index("LibraryImportTask_libraryId_kind_idx", "libraryId", "kind", "state"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_anchor_node_id: Mapped[str | None] = mapped_column(
        "resourceAnchorNodeId", String(191), nullable=True
    )
    rerun_requested: Mapped[bool] = mapped_column(
        "rerunRequested", Boolean, nullable=False, default=False, server_default="0"
    )
    scan_scopes: Mapped[str | None] = mapped_column("scanScopes", Text, nullable=True)
    book_metadata_revision: Mapped[int | None] = mapped_column(
        "bookMetadataRevision", Integer, nullable=True
    )
    book_id: Mapped[str | None] = mapped_column("bookId", String(191), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_version: Mapped[int] = mapped_column(
        "requestVersion", Integer, nullable=False, default=0, server_default="0"
    )
    execution_version: Mapped[int | None] = mapped_column(
        "executionVersion", Integer, nullable=True
    )
    book_work: Mapped[str | None] = mapped_column("bookWork", Text, nullable=True)
    # NULL means the durable scan gap changed and this projection needs refresh.
    scan_gate_blocked: Mapped[bool | None] = mapped_column(
        "scanGateBlocked", Boolean, nullable=True
    )
    resource_cursor: Mapped[str | None] = mapped_column(
        "resourceCursor", String(191), nullable=True
    )
    # One active directory resource's visited member position within a Book run.
    directory_resource_id: Mapped[str | None] = mapped_column(
        "directoryResourceId", String(191), nullable=True
    )
    directory_member_cursor: Mapped[str | None] = mapped_column(
        "directoryMemberCursor", String(191), nullable=True
    )
    directory_cover_cursor: Mapped[str | None] = mapped_column(
        "directoryCoverCursor", String(191), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(
        "retryCount", Integer, nullable=False, default=0, server_default="0"
    )
    # A committed Book business result awaiting only its terminal task write.
    completion_outcome: Mapped[str | None] = mapped_column(
        "completionOutcome", String(32), nullable=True
    )
    completion_retry_count: Mapped[int] = mapped_column(
        "completionRetryCount", Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        "nextAttemptAt", TimestampMilliseconds(), nullable=True
    )
    superseded_by_task_id: Mapped[str | None] = mapped_column(
        "supersededByTaskId", String(191), nullable=True
    )
    library_id: Mapped[str] = mapped_column(
        "libraryId",
        String(191),
        ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str | None] = mapped_column(
        "resourceId", String(191), nullable=True
    )
    source_node_id: Mapped[str | None] = mapped_column(
        "sourceNodeId", String(191), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="QUEUED",
        server_default="QUEUED",
    )
    error_summary: Mapped[str | None] = mapped_column(
        "errorSummary", Text, nullable=True
    )
    missing_entry_policy: Mapped[str] = mapped_column(
        "missingEntryPolicy",
        String(32),
        nullable=False,
        default="PRESERVE",
        server_default="PRESERVE",
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        "startedAt", TimestampMilliseconds(), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        "finishedAt", TimestampMilliseconds(), nullable=True
    )
    resource: Mapped[LibraryReadableResource | None] = relationship(
        foreign_keys=[resource_id, library_id],
        primaryjoin=(
            "and_(LibraryImportTask.resource_id==LibraryReadableResource.id,"
            "LibraryImportTask.library_id==LibraryReadableResource.library_id)"
        ),
    )
    source_node: Mapped[LibrarySourceNode | None] = relationship(
        foreign_keys=[source_node_id, library_id],
        primaryjoin=(
            "and_(LibraryImportTask.source_node_id==LibrarySourceNode.id,"
            "LibraryImportTask.library_id==LibrarySourceNode.library_id)"
        ),
        overlaps="resource",
    )


__all__ = ["LibraryImportScanGap", "LibraryImportTask"]

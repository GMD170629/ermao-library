"""Fresh-baseline ORM table for the single-consumer ContinueImport task."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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


class LibraryImportTask(Base):
    """Single-consumer ContinueImport task."""

    __tablename__ = "LibraryImportTask"
    __table_args__ = (
        CheckConstraint(
            column("kind").in_(("SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET")),
            name="LibraryImportTask_kind_check",
        ),
        CheckConstraint(
            column("state").in_(("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")),
            name="LibraryImportTask_state_check",
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
                    column("kind") == "CONTINUE_SOURCE",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind") == "IMPORT_ASSET",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_not(None),
                    column("role").is_not(None),
                ),
            ),
            name="LibraryImportTask_kind_shape_check",
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
            "LibraryImportTask_import_asset_key",
            "resourceId",
            "sourceNodeId",
            unique=True,
            sqlite_where=column("kind") == "IMPORT_ASSET",
        ),
        Index("LibraryImportTask_queued_createdAt_idx", "state", "createdAt"),
        Index("LibraryImportTask_libraryId_kind_idx", "libraryId", "kind", "state"),
        Index(
            "LibraryImportTask_scan_queued_key",
            "libraryId",
            unique=True,
            sqlite_where=and_(
                column("kind") == "SCAN_LIBRARY",
                column("state") == "QUEUED",
            ),
        ),
        Index(
            "LibraryImportTask_scan_running_key",
            "libraryId",
            unique=True,
            sqlite_where=and_(
                column("kind") == "SCAN_LIBRARY",
                column("state") == "RUNNING",
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
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


__all__ = ["LibraryImportTask"]

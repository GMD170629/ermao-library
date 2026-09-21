"""Shared durable file-write conflicts for import, move and writeback claims."""

from sqlalchemy import SQLColumnExpression, String, cast, func, literal, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    LibraryFileMoveOperation,
    LibraryFileMovePlan,
    LibraryFileMoveTarget,
    MetadataStandardWriteOperation,
    MetadataStandardWritePlan,
    MetadataStandardWriteTarget,
)
from app.models.organize import MetadataWritebackTarget


def standard_write_blocks_library(
    library_id: SQLColumnExpression[str],
) -> ColumnElement[bool]:
    queue = aliased(MetadataWritebackTarget)
    return (
        select(MetadataStandardWriteTarget.operation_id)
        .join(queue, queue.id == MetadataStandardWriteTarget.queue_target_id)
        .where(
            MetadataStandardWriteTarget.library_id == library_id,
            queue.status.in_(("RUNNING", "PREPARED", "REVIEW")),
        )
        .exists()
    )


def file_operation_blocks_library(
    library_id: SQLColumnExpression[str],
) -> ColumnElement[bool]:
    return or_(
        LibraryFileMoveOperation.blocks_library(library_id),
        standard_write_blocks_library(library_id),
    )


def recovery_holds_source_nodes(db: Session, node_ids: tuple[str, ...]) -> bool:
    """Do not relocate a published file while its backup still needs that locator.

    Plans remain immutable. The ordinal selects a server-created plan item, never
    an input JSON path; current source-node IDs also cover a moved parent directory.
    """
    write_node = func.json_extract(
        MetadataStandardWritePlan.payload,
        literal("$.targets[")
        + cast(MetadataStandardWriteTarget.ordinal, String)
        + literal("].source_node_id"),
    )
    pending_write = (
        select(MetadataStandardWriteTarget.operation_id)
        .join(
            MetadataStandardWriteOperation,
            MetadataStandardWriteOperation.id
            == MetadataStandardWriteTarget.operation_id,
        )
        .join(
            MetadataStandardWritePlan,
            MetadataStandardWritePlan.id == MetadataStandardWriteOperation.plan_id,
        )
        .where(
            MetadataStandardWriteTarget.stage == "COMPLETED",
            MetadataStandardWriteTarget.recovery_released.is_(False),
            write_node.in_(node_ids),
        )
        .limit(1)
    )
    if db.scalar(pending_write) is not None:
        return True
    moved_node = func.json_extract(
        LibraryFileMovePlan.payload,
        literal("$.moves[")
        + cast(LibraryFileMoveTarget.ordinal, String)
        + literal("].source.node_id"),
    )
    return (
        db.scalar(
            select(LibraryFileMoveTarget.operation_id)
            .join(
                LibraryFileMoveOperation,
                LibraryFileMoveOperation.id == LibraryFileMoveTarget.operation_id,
            )
            .join(
                LibraryFileMovePlan,
                LibraryFileMovePlan.id == LibraryFileMoveOperation.plan_id,
            )
            .where(
                LibraryFileMoveTarget.stage == "COMPLETED",
                LibraryFileMoveTarget.copy_required.is_(True),
                LibraryFileMoveTarget.recovery["source_backup_cleared_at"]
                .as_integer()
                .is_(None),
                moved_node.in_(node_ids),
            )
            .limit(1)
        )
        is not None
    )

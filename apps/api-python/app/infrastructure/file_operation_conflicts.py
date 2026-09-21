"""Shared durable file-write conflicts for import, move and writeback claims."""

from sqlalchemy import SQLColumnExpression, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import LibraryFileMoveOperation, MetadataStandardWriteTarget
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

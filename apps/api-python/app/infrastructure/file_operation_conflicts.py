"""Active file-write conflicts shared by import, move and writeback claims."""

from datetime import UTC, datetime

from sqlalchemy import SQLColumnExpression, and_, func, or_, select, true
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    AutomationUploadRow,
    FileDeletePlanRow,
    LibraryFileMoveOperation,
    MetadataStandardWriteTarget,
)
from app.models.organize import MetadataWritebackTarget


def writeback_has_live_lease(
    status: SQLColumnExpression[str],
    lease_expires_at: SQLColumnExpression[datetime | None],
    now: datetime,
) -> ColumnElement[bool]:
    return and_(status.in_(("RUNNING", "PREPARED")), lease_expires_at > now)


def standard_write_blocks_library(
    library_id: SQLColumnExpression[str],
    now: datetime,
) -> ColumnElement[bool]:
    queue = aliased(MetadataWritebackTarget)
    return (
        select(MetadataStandardWriteTarget.operation_id)
        .join(queue, queue.id == MetadataStandardWriteTarget.queue_target_id)
        .where(
            MetadataStandardWriteTarget.library_id == library_id,
            writeback_has_live_lease(queue.status, queue.lease_expires_at, now),
        )
        .exists()
    )


def file_operation_blocks_library(
    library_id: SQLColumnExpression[str],
    now: datetime | None = None,
) -> ColumnElement[bool]:
    targets = (
        func.json_each(FileDeletePlanRow.payload, "$.targets")
        .table_valued("value")
        .alias("delete_targets")
    )
    deletion = (
        select(FileDeletePlanRow.id)
        .select_from(FileDeletePlanRow)
        .join(targets, true())
        .where(
            FileDeletePlanRow.payload["executing"].as_boolean().is_(True),
            func.json_extract(targets.c.value, "$.source.library_id") == library_id,
            or_(
                func.json_extract(targets.c.value, "$.stage").in_(
                    ("STAGING", "STAGED")
                ),
                and_(
                    func.json_extract(targets.c.value, "$.stage") == "QUEUED",
                    FileDeletePlanRow.payload["cancelled"].as_boolean().is_(False),
                ),
            ),
        )
        .exists()
    )
    replacement = (
        select(AutomationUploadRow.id)
        .where(
            AutomationUploadRow.library_id == library_id,
            AutomationUploadRow.payload["spec"]["purpose"].as_string() == "replace",
            AutomationUploadRow.status.in_(
                ("PUBLISHING", "SAVED", "RECOVERY_REQUIRED")
            ),
        )
        .exists()
    )
    return or_(
        deletion,
        replacement,
        LibraryFileMoveOperation.blocks_library(library_id),
        standard_write_blocks_library(library_id, now or datetime.now(UTC)),
    )

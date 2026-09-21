"""One recovery-space accounting query for file moves and metadata replacement."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LibraryFileMoveTarget, MetadataStandardWriteTarget


def reserved_file_recovery_bytes(db: Session) -> int:
    moves = db.scalar(
        select(func.coalesce(func.sum(LibraryFileMoveTarget.byte_count), 0)).where(
            LibraryFileMoveTarget.copy_required.is_(True),
            LibraryFileMoveTarget.stage.not_in(("FAILED", "CANCELLED")),
            LibraryFileMoveTarget.recovery["source_backup_cleared_at"]
            .as_integer()
            .is_(None),
        )
    )
    metadata = db.scalar(
        select(
            func.coalesce(func.sum(MetadataStandardWriteTarget.reserved_bytes), 0)
        ).where(
            MetadataStandardWriteTarget.stage.not_in(("FAILED", "CANCELLED")),
            MetadataStandardWriteTarget.recovery_released.is_(False),
        )
    )
    return int(moves or 0) + int(metadata or 0)

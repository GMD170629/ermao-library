"""System-owned persistence projections for the management overview."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DownloadTask,
    LibraryImportTask,
    LibraryResourceAsset,
    LibrarySourceNode,
    OrganizeJob,
    SystemEvent,
)


def management_card_counts(db: Session) -> dict[str, int]:
    failed_imports = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryImportTask)
            .where(LibraryImportTask.state == "FAILED")
        )
        or 0
    )
    failed_downloads = int(
        db.scalar(
            select(func.count())
            .select_from(DownloadTask)
            .where(DownloadTask.status == "failed")
        )
        or 0
    )
    pending_organize = int(
        db.scalar(
            select(func.count())
            .select_from(OrganizeJob)
            .where(
                OrganizeJob.status.in_(
                    (
                        "LOOKUP_PENDING",
                        "PENDING",
                        "QUEUED",
                        "RUNNING",
                        "RETRY_WAIT",
                        "REVIEWING",
                        "FAILED",
                    )
                )
            )
        )
        or 0
    )
    storage = int(
        db.scalar(
            select(func.coalesce(func.sum(LibrarySourceNode.observed_size_bytes), 0))
            .select_from(LibraryResourceAsset)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(LibraryResourceAsset.import_state == "READY")
        )
        or 0
    )
    return {
        "failedImports": failed_imports,
        "failedDownloads": failed_downloads,
        "pendingOrganize": pending_organize,
        "managedStorageBytes": storage,
    }


def recent_system_events(db: Session, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "level": row.level,
            "source": row.source,
            "actorType": row.actor_type,
            "actorId": row.actor_id,
            "action": row.action,
            "targetType": row.target_type,
            "targetId": row.target_id,
            "message": row.message,
            "metadata": row.metadata_json,
            "createdAt": row.created_at,
        }
        for row in rows
    ]

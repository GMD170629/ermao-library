"""Dashboard projections for the canonical library import task queue."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Library, LibraryImportTask


class LibraryImportDashboardSnapshot(TypedDict):
    enabled_libraries: list[dict[str, object]]
    current_task: dict[str, object] | None
    latest_task: dict[str, object] | None
    failed_count: int


def _library_view(row: Library) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "rootPath": row.root_path,
        "organizationMode": row.organization_mode,
        "enabled": bool(row.enabled),
        "ignorePatterns": row.ignore_patterns,
        "ignoreHidden": bool(row.ignore_hidden),
        "minFileSizeBytes": row.min_file_size_bytes,
        "description": row.description,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def _task_view(row: LibraryImportTask) -> dict[str, object]:
    return {
        "id": row.id,
        "kind": row.kind,
        "libraryId": row.library_id,
        "resourceId": row.resource_id,
        "sourceNodeId": row.source_node_id,
        "role": row.role,
        "state": row.state,
        "errorSummary": row.error_summary,
        "createdAt": row.created_at,
        "startedAt": row.started_at,
        "finishedAt": row.finished_at,
    }


def library_import_dashboard_snapshot(
    db: Session,
) -> LibraryImportDashboardSnapshot:
    """Return one bounded, target-identity dashboard projection."""

    enabled_libraries = [
        _library_view(row)
        for row in db.scalars(
            select(Library)
            .where(Library.enabled.is_(True))
            .order_by(Library.created_at.desc(), Library.id.desc())
        ).all()
    ]
    current = db.scalar(
        select(LibraryImportTask)
        .where(LibraryImportTask.state.in_(("QUEUED", "RUNNING")))
        .order_by(LibraryImportTask.created_at.asc(), LibraryImportTask.id.asc())
        .limit(1)
    )
    latest = db.scalar(
        select(LibraryImportTask)
        .order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id.desc())
        .limit(1)
    )
    failed_count = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryImportTask)
            .where(LibraryImportTask.state == "FAILED")
        )
        or 0
    )
    return {
        "enabled_libraries": enabled_libraries,
        "current_task": _task_view(current) if current is not None else None,
        "latest_task": _task_view(latest) if latest is not None else None,
        "failed_count": failed_count,
    }


__all__ = ["LibraryImportDashboardSnapshot", "library_import_dashboard_snapshot"]

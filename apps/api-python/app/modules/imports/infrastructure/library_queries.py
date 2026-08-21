"""ORM projections used by the import HTTP and composition boundaries.

The import capability owns the library-root commands because enabling a root is
also an import decision.  This module deliberately exposes projections rather
than ORM entities to presentation code and contains no queue compatibility
queries.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    library_visibility_predicate,
)
from app.models import (
    Library,
    LibraryImportTask,
    LibrarySourceNode,
    UserLibraryAccess,
)


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


def list_libraries(db: Session) -> list[dict[str, object]]:
    rows = db.scalars(
        select(Library).order_by(Library.created_at.desc(), Library.id.desc())
    ).all()
    return [_library_view(row) for row in rows]


def list_enabled_library_rows(db: Session) -> list[dict[str, object]]:
    rows = db.scalars(
        select(Library)
        .where(Library.enabled.is_(True))
        .order_by(Library.created_at.desc(), Library.id.desc())
    ).all()
    return [_library_view(row) for row in rows]


def list_library_root_paths(db: Session) -> tuple[str, ...]:
    rows = db.scalars(
        select(Library.root_path)
        .where(Library.root_path.is_not(None))
        .order_by(Library.created_at.desc(), Library.id.desc())
    ).all()
    return tuple(str(path) for path in rows if path)


def get_library(db: Session, library_id: str) -> dict[str, object] | None:
    row = db.get(Library, library_id)
    return None if row is None else _library_view(row)


def get_library_by_root_path(
    db: Session,
    root_path: str,
    *,
    exclude_id: str | None = None,
) -> dict[str, object] | None:
    filters = [Library.root_path == root_path]
    if exclude_id is not None:
        filters.append(Library.id != exclude_id)
    row = db.scalar(select(Library).where(*filters).limit(1))
    return None if row is None else _library_view(row)


def library_has_topology(db: Session, library_id: str) -> bool:
    return bool(
        db.scalar(select(exists().where(LibrarySourceNode.library_id == library_id)))
    )


def list_library_access_user_ids(db: Session, library_id: str) -> tuple[str, ...]:
    return tuple(
        str(user_id)
        for user_id in db.scalars(
            select(UserLibraryAccess.user_id).where(
                UserLibraryAccess.library_id == library_id
            )
        ).all()
    )


def library_id_for_path(db: Session, target: Path) -> str | None:
    try:
        resolved_target = target.expanduser().resolve()
    except OSError:
        return None
    for row in db.scalars(select(Library).where(Library.enabled.is_(True))).all():
        try:
            root = Path(row.root_path).expanduser().resolve()
            resolved_target.relative_to(root)
        except (OSError, ValueError):
            continue
        return row.id
    return None


def source_node_library_id(db: Session, source_node_id: str) -> str | None:
    return db.scalar(
        select(LibrarySourceNode.library_id).where(
            LibrarySourceNode.id == source_node_id
        )
    )


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


def get_import_task(
    db: Session,
    task_id: str,
    context: AuthorizationContext | None = None,
) -> dict[str, object] | None:
    row = db.get(LibraryImportTask, task_id)
    if row is None:
        return None
    if context is not None:
        visible = db.scalar(
            select(LibraryImportTask.id).where(
                LibraryImportTask.id == task_id,
                library_visibility_predicate(context, LibraryImportTask.library_id),
            )
        )
        if visible is None:
            return None
    return _task_view(row)


def list_import_tasks_page(
    db: Session,
    context: AuthorizationContext,
    *,
    page: int,
    page_size: int,
    library_id: str | None = None,
    state: str | None = None,
) -> tuple[list[dict[str, object]], int, dict[str, int]]:
    scope = library_visibility_predicate(context, LibraryImportTask.library_id)
    filters = [scope]
    if library_id is not None:
        filters.append(LibraryImportTask.library_id == library_id)
    normalized_state = str(state or "").strip().upper()
    if normalized_state and normalized_state != "ALL":
        filters.append(LibraryImportTask.state == normalized_state)
    total = int(
        db.scalar(select(func.count()).select_from(LibraryImportTask).where(*filters))
        or 0
    )
    completed = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryImportTask)
            .where(*filters, LibraryImportTask.state == "SUCCEEDED")
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryImportTask)
            .where(*filters, LibraryImportTask.state == "FAILED")
        )
        or 0
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    normalized_page = min(max(1, page), total_pages)
    rows = db.scalars(
        select(LibraryImportTask)
        .where(*filters)
        .order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id.desc())
        .limit(page_size)
        .offset((normalized_page - 1) * page_size)
    ).all()
    return (
        [_task_view(row) for row in rows],
        total,
        {"completed": completed, "failed": failed},
    )


__all__ = [
    "get_import_task",
    "get_library",
    "get_library_by_root_path",
    "library_has_topology",
    "library_id_for_path",
    "list_enabled_library_rows",
    "list_import_tasks_page",
    "list_libraries",
    "list_library_access_user_ids",
    "list_library_root_paths",
    "source_node_library_id",
]

"""ORM projections used by the import HTTP and composition boundaries.

The import capability owns the library-root commands because enabling a root is
also an import decision.  This module deliberately exposes projections rather
than ORM entities to presentation code and contains no queue compatibility
queries.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    library_visibility_predicate,
)
from app.core.exception_diagnostics import record_exception
from app.models import (
    Library,
    LibraryBookMetadata,
    LibraryImportScanGap,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
    UserLibraryAccess,
)
from app.modules.imports.domain.scan_policy import (
    decode_scan_scopes,
    paths_intersect,
    scope_covers_path,
    scopes_cover_path,
)

_DIRECTORY_FORMATS = ("IMAGE_DIR", "AUDIOBOOK_DIR")
_WAITING_KINDS = ("IMPORT_BOOK", "IMPORT_RESOURCE", "IDENTIFY_BOOK")


def _library_view(row: Library) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "rootPath": row.root_path,
        "organizationMode": row.organization_mode,
        "enabled": bool(row.enabled),
        "ignorePatterns": row.ignore_patterns,
        "ignoreHidden": bool(row.ignore_hidden),
        "allowEmptyLibraryCleanup": bool(row.allow_empty_library_cleanup),
        "minFileSizeBytes": row.min_file_size_bytes,
        "description": row.description,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def _library_display_order() -> tuple[ColumnElement[object], ...]:
    return (
        Library.sort_order.asc(),
        Library.created_at.desc(),
        Library.id.desc(),
    )


def list_libraries(db: Session) -> list[dict[str, object]]:
    rows = db.scalars(select(Library).order_by(*_library_display_order())).all()
    return [_library_view(row) for row in rows]


def list_enabled_library_rows(db: Session) -> list[dict[str, object]]:
    rows = db.scalars(
        select(Library)
        .where(Library.enabled.is_(True))
        .order_by(*_library_display_order())
    ).all()
    return [_library_view(row) for row in rows]


def list_library_root_paths(db: Session) -> tuple[str, ...]:
    rows = db.scalars(
        select(Library.root_path)
        .where(Library.root_path.is_not(None))
        .order_by(*_library_display_order())
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
    except OSError as error:
        record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.library_queries.library_id_for_path.failed", error,
                         context={"step": "library_id_for_path"})
        return None
    for row in db.scalars(select(Library).where(Library.enabled.is_(True))).all():
        try:
            root = Path(row.root_path).expanduser().resolve()
            resolved_target.relative_to(root)
        except (OSError, ValueError) as error:
            record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.library_queries.library_id_for_path.failed", error,
                             context={"step": "library_id_for_path"})
            continue
        return row.id
    return None


def source_node_library_id(db: Session, source_node_id: str) -> str | None:
    return db.scalar(
        select(LibrarySourceNode.library_id).where(
            LibrarySourceNode.id == source_node_id
        )
    )


def _task_view(
    row: LibraryImportTask,
    *,
    library_name: str,
    source_name: str | None,
    source_relative_path: str | None,
    resource_title: str | None,
    book_title: str | None,
) -> dict[str, object]:
    return {
        "id": row.id,
        "kind": row.kind,
        "libraryId": row.library_id,
        "libraryName": library_name,
        "resourceId": row.resource_id,
        "resourceTitle": resource_title,
        "sourceNodeId": row.source_node_id,
        "sourceName": source_name,
        "sourceRelativePath": source_relative_path,
        "bookTitle": book_title,
        "role": row.role,
        "state": row.state,
        "errorSummary": row.error_summary,
        "waitingFor": None,
        "createdAt": row.created_at,
        "startedAt": row.started_at,
        "finishedAt": row.finished_at,
    }


def _attach_waiting_reasons(db: Session, views: list[dict[str, object]]) -> None:
    """Explain, read-only, why a queued task is not yet executable.

    Reasons come from durable scan gaps and active work; no state is written
    and waiting tasks stay ``QUEUED``.
    """
    queued = [
        view
        for view in views
        if view.get("state") == "QUEUED" and view.get("kind") in _WAITING_KINDS
    ]
    if not queued:
        return
    library_ids = {str(view.get("libraryId")) for view in queued}
    book_ids = {
        str(view["id"]) for view in queued if view.get("kind") == "IMPORT_BOOK"
    }
    book_claims = {
        str(task_id): (str(phase), str(physical_kind))
        for task_id, phase, physical_kind in db.execute(
            select(
                LibraryImportTask.id,
                LibraryImportTask.phase,
                LibrarySourceNode.physical_kind,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryImportTask.source_node_id,
            )
            .where(LibraryImportTask.id.in_(book_ids))
        ).all()
    } if book_ids else {}
    resource_ids = {
        str(view.get("resourceId"))
        for view in queued
        if view.get("kind") == "IMPORT_RESOURCE" and view.get("resourceId")
    }
    directory_resource_ids: set[str] = set()
    if resource_ids:
        directory_resource_ids = {
            str(value)
            for value in db.scalars(
                select(LibraryReadableResource.id).where(
                    LibraryReadableResource.id.in_(resource_ids),
                    LibraryReadableResource.format.in_(_DIRECTORY_FORMATS),
                )
            ).all()
        }
    gaps: dict[str, list[object]] = {}
    for library_id, scopes_json in db.execute(
        select(
            LibraryImportScanGap.library_id, LibraryImportScanGap.scopes
        ).where(LibraryImportScanGap.library_id.in_(library_ids))
    ).all():
        gaps[str(library_id)] = list(decode_scan_scopes(scopes_json) or ())
    scans: dict[str, list[tuple[str, str, tuple[object, ...] | None]]] = {}
    for library_id, kind, path, scopes_json in db.execute(
        select(
            LibraryImportTask.library_id,
            LibraryImportTask.kind,
            LibrarySourceNode.relative_path,
            LibraryImportTask.scan_scopes,
        )
        .select_from(LibraryImportTask)
        .outerjoin(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryImportTask.source_node_id,
        )
        .where(
            LibraryImportTask.library_id.in_(library_ids),
            LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")),
            LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
        )
    ).all():
        scans.setdefault(str(library_id), []).append(
            (
                str(kind),
                str(path) if path is not None else "",
                decode_scan_scopes(scopes_json),
            )
        )
    active_imports: dict[str, list[str]] = {}
    for library_id, path in db.execute(
        select(LibraryImportTask.library_id, LibrarySourceNode.relative_path)
        .select_from(LibraryImportTask)
        .outerjoin(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryImportTask.source_node_id,
        )
        .where(
            LibraryImportTask.library_id.in_(library_ids),
            LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE")),
            LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
        )
    ).all():
        active_imports.setdefault(str(library_id), []).append(
            str(path) if path is not None else ""
        )
    for view in queued:
        if view.get("kind") == "IMPORT_BOOK" and (
            book_claims.get(str(view["id"]), (None, None))[0] == "SCAN"
            or book_claims.get(str(view["id"]), (None, None))[1]
            == "REGULAR_FILE"
        ):
            continue
        if view.get("kind") == "IMPORT_RESOURCE" and str(
            view.get("resourceId") or ""
        ) not in directory_resource_ids:
            continue
        library_id = str(view.get("libraryId"))
        anchor = str(view.get("sourceRelativePath") or "")
        gap_scope = next(
            (
                scope
                for scope in gaps.get(library_id, ())
                if scope_covers_path(scope, anchor)  # type: ignore[arg-type]
            ),
            None,
        )
        if gap_scope is not None:
            view["waitingFor"] = {
                "reason": "SCAN_INCOMPLETE",
                "scope": getattr(gap_scope, "relative_path", ""),
                "recovery": "RETRY_SCAN",
            }
            continue
        # Only identification waits on active work. A directory resource is
        # executable in creation order, so announcing an active scan would
        # contradict the scheduler's actual selection.
        if view.get("kind") != "IDENTIFY_BOOK":
            continue
        for kind, path, scopes in scans.get(library_id, ()):
            if kind == "SCAN_LIBRARY":
                covered = scopes is None or scopes_cover_path(scopes, anchor)  # type: ignore[arg-type]
            else:
                covered = paths_intersect(path, anchor)
            if covered:
                view["waitingFor"] = {
                    "reason": "SCAN_ACTIVE",
                    "scope": path,
                    "recovery": None,
                }
                break
        if view["waitingFor"] is not None:
            continue
        if view.get("kind") == "IDENTIFY_BOOK" and any(
            path_contains_anchor(path, anchor)
            for path in active_imports.get(library_id, ())
        ):
            view["waitingFor"] = {
                "reason": "IMPORT_ACTIVE",
                "scope": None,
                "recovery": None,
            }


def path_contains_anchor(candidate: str, anchor: str) -> bool:
    """True when an active import path can change the anchor's inputs."""
    return candidate == anchor or anchor == "" or candidate.startswith(anchor + "/")


def _task_projection_statement():
    return (
        select(
            LibraryImportTask,
            Library.name.label("library_name"),
            LibrarySourceNode.name.label("source_name"),
            LibrarySourceNode.relative_path.label("source_relative_path"),
            LibraryReadableResourceMetadata.title.label("resource_title"),
            LibraryBookMetadata.title.label("book_title"),
        )
        .join(Library, Library.id == LibraryImportTask.library_id)
        .outerjoin(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryImportTask.source_node_id,
        )
        .outerjoin(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryImportTask.resource_id,
        )
        .outerjoin(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .outerjoin(
            LibraryBookMetadata,
            LibraryBookMetadata.book_id
            == func.coalesce(
                LibraryImportTask.book_id, LibraryReadableResource.book_id
            ),
        )
    )


def _project_task_row(
    row: Row[
        tuple[
            LibraryImportTask,
            str,
            str | None,
            str | None,
            str | None,
            str | None,
        ]
    ],
) -> dict[str, object]:
    (
        task,
        library_name,
        source_name,
        source_relative_path,
        resource_title,
        book_title,
    ) = row
    return _task_view(
        task,
        library_name=library_name,
        source_name=source_name,
        source_relative_path=source_relative_path,
        resource_title=resource_title,
        book_title=book_title,
    )


def get_import_task(
    db: Session,
    task_id: str,
    context: AuthorizationContext | None = None,
) -> dict[str, object] | None:
    filters = [LibraryImportTask.id == task_id]
    if context is not None:
        filters.append(
            library_visibility_predicate(
                context,
                cast(ColumnElement[str], LibraryImportTask.library_id),
            )
        )
    row = db.execute(_task_projection_statement().where(*filters)).one_or_none()
    if row is None:
        return None
    current_id = row[0].superseded_by_task_id
    if current_id is not None:
        current_filters = [
            LibraryImportTask.id == current_id,
            LibraryImportTask.library_id == row[0].library_id,
        ]
        if context is not None:
            current_filters.append(
                library_visibility_predicate(
                    context,
                    cast(ColumnElement[str], LibraryImportTask.library_id),
                )
            )
        row = db.execute(
            _task_projection_statement().where(*current_filters)
        ).one_or_none()
        if row is None:
            return None
    view = _project_task_row(row)
    _attach_waiting_reasons(db, [view])
    return view


def list_import_tasks_page(
    db: Session,
    context: AuthorizationContext,
    *,
    page: int,
    page_size: int,
    library_id: str | None = None,
    state: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict[str, object]], int, dict[str, int]]:
    scope = library_visibility_predicate(
        context,
        cast(ColumnElement[str], LibraryImportTask.library_id),
    )
    scope_filters = [scope, LibraryImportTask.superseded_by_task_id.is_(None)]
    if library_id is not None:
        scope_filters.append(LibraryImportTask.library_id == library_id)
    filters = list(scope_filters)
    normalized_state = str(state or "").strip().upper()
    if normalized_state and normalized_state != "ALL":
        filters.append(LibraryImportTask.state == normalized_state)
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        matching_task_ids = (
            _task_projection_statement()
            .with_only_columns(LibraryImportTask.id)
            .where(
                or_(
                    LibrarySourceNode.name.icontains(
                        normalized_keyword, autoescape=True
                    ),
                    LibrarySourceNode.relative_path.icontains(
                        normalized_keyword, autoescape=True
                    ),
                    LibraryReadableResourceMetadata.title.icontains(
                        normalized_keyword, autoescape=True
                    ),
                    LibraryBookMetadata.title.icontains(
                        normalized_keyword, autoescape=True
                    ),
                )
            )
        )
        filters.append(LibraryImportTask.id.in_(matching_task_ids))
    total = int(
        db.scalar(select(func.count()).select_from(LibraryImportTask).where(*filters))
        or 0
    )
    summary = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
    summary_keys = {
        "QUEUED": "queued",
        "RUNNING": "running",
        "SUCCEEDED": "completed",
        "FAILED": "failed",
    }
    summary_rows = db.execute(
        select(
            LibraryImportTask.kind,
            LibraryImportTask.state,
            func.count().label("task_count"),
        )
        .where(*scope_filters)
        .group_by(LibraryImportTask.kind, LibraryImportTask.state)
    ).all()
    for summary_row in summary_rows:
        key = summary_keys.get(str(summary_row.state))
        if key is not None:
            summary[key] += int(summary_row.task_count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    normalized_page = min(max(1, page), total_pages)
    page_task_ids = (
        select(LibraryImportTask.id.label("task_id"))
        .where(*filters)
        .order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id.desc())
        .limit(page_size)
        .offset((normalized_page - 1) * page_size)
        .subquery()
    )
    rows = db.execute(
        _task_projection_statement()
        .join(page_task_ids, page_task_ids.c.task_id == LibraryImportTask.id)
        .order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id.desc())
    ).all()
    views = [_project_task_row(row) for row in rows]
    _attach_waiting_reasons(db, views)
    return (
        views,
        total,
        summary,
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

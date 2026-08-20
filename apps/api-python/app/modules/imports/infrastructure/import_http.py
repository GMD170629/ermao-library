"""ORM helpers for import-task and library HTTP adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, delete, exists, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    library_visibility_predicate,
)
from app.models.auth import User, UserLibraryAccess
from app.models.import_pipeline import (
    ImportAsset,
    ImportLog,
    ImportTask,
)
from app.models.library import Library, LibraryWork


def get_import_task(db: Session, task_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(select(ImportTask.__table__).where(ImportTask.id == task_id))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_import_tasks_page(
    db: Session,
    context: AuthorizationContext,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    filters: list[Any] = [library_visibility_predicate(context, ImportTask.library_id)]
    normalized_status = str(status or "").strip().upper()
    if normalized_status and normalized_status != "ALL":
        filters.append(ImportTask.status == normalized_status)

    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        title_match = exists(
            select(LibraryWork.id).where(
                LibraryWork.id == ImportTask.work_id,
                LibraryWork.title.like(pattern),
            )
        )
        filters.append(
            or_(
                ImportTask.original_name.like(pattern),
                ImportTask.source_path.like(pattern),
                func.coalesce(ImportTask.message, "").like(pattern),
                func.coalesce(ImportTask.error_summary, "").like(pattern),
                title_match,
            )
        )

    scope = library_visibility_predicate(context, ImportTask.library_id)
    scope_counts = db.execute(
        select(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((ImportTask.status == "COMPLETED", 1), else_=0)),
                0,
            ).label("completed"),
            func.coalesce(
                func.sum(case((ImportTask.status == "FAILED", 1), else_=0)),
                0,
            ).label("failed"),
        )
        .select_from(ImportTask)
        .where(scope)
    ).one()
    has_filtered_total = bool(
        (normalized_status and normalized_status != "ALL") or normalized_keyword
    )
    total = (
        int(
            db.scalar(select(func.count()).select_from(ImportTask).where(*filters)) or 0
        )
        if has_filtered_total
        else int(scope_counts.total or 0)
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    rows = (
        db.execute(
            select(ImportTask.__table__)
            .where(*filters)
            .order_by(ImportTask.created_at.desc(), ImportTask.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .mappings()
        .all()
    )
    tasks = [dict(row) for row in rows]

    summary = {
        "completed": int(scope_counts.completed or 0),
        "failed": int(scope_counts.failed or 0),
    }
    return tasks, total, summary


def hydrate_import_task_page(
    db: Session,
    tasks: list[dict[str, Any]],
    *,
    log_limit: int,
) -> list[dict[str, Any]]:
    """Attach page-scoped related records without per-task database queries."""

    if not tasks:
        return []
    task_ids = [str(task["id"]) for task in tasks]
    library_ids = {str(task["libraryId"]) for task in tasks if task.get("libraryId")}
    work_ids = {str(task["workId"]) for task in tasks if task.get("workId")}

    libraries = {
        str(row["id"]): dict(row)
        for row in db.execute(
            select(Library.__table__).where(Library.id.in_(library_ids))
        )
        .mappings()
        .all()
    }
    works = {
        str(row.id): {"id": row.id, "title": row.title}
        for row in db.execute(
            select(LibraryWork.id, LibraryWork.title).where(
                LibraryWork.id.in_(work_ids)
            )
        ).all()
    }

    log_rank = (
        func.row_number()
        .over(
            partition_by=ImportLog.import_task_id,
            order_by=(ImportLog.created_at.desc(), ImportLog.id.desc()),
        )
        .label("page_rank")
    )
    ranked_logs = (
        select(ImportLog.__table__, log_rank)
        .where(ImportLog.import_task_id.in_(task_ids))
        .subquery()
    )
    logs_by_task_id = {task_id: [] for task_id in task_ids}
    if log_limit > 0:
        for row in (
            db.execute(
                select(ranked_logs)
                .where(ranked_logs.c.page_rank <= log_limit)
                .order_by(
                    ranked_logs.c.importTaskId,
                    ranked_logs.c.createdAt.desc(),
                    ranked_logs.c.id.desc(),
                )
            )
            .mappings()
            .all()
        ):
            log = dict(row)
            log.pop("page_rank", None)
            logs_by_task_id[str(row["importTaskId"])].append(log)

    return [
        {
            **task,
            "_pageLibrary": libraries.get(str(task.get("libraryId") or "")),
            "_pageWork": works.get(str(task.get("workId") or "")),
            "_pageLogs": logs_by_task_id[str(task["id"])],
        }
        for task in tasks
    ]


def clear_terminal_import_tasks(db: Session, context: AuthorizationContext) -> int:
    scope = library_visibility_predicate(context, ImportTask.library_id)
    result = db.execute(
        delete(ImportTask).where(
            ImportTask.status.in_(("COMPLETED", "FAILED")),
            scope,
        )
    )
    return int(result.rowcount or 0)


def list_terminal_import_task_ids(
    db: Session,
    context: AuthorizationContext,
) -> tuple[str, ...]:
    scope = library_visibility_predicate(context, ImportTask.library_id)
    return tuple(
        str(task_id)
        for task_id in db.scalars(
            select(ImportTask.id).where(
                ImportTask.status.in_(("COMPLETED", "FAILED")),
                scope,
            )
        ).all()
    )


def delete_import_task_row(db: Session, task_id: str) -> bool:
    result = db.execute(delete(ImportTask).where(ImportTask.id == task_id))
    return bool(result.rowcount)


def reset_import_assets_for_retry(
    db: Session, task_id: str, *, updated_at: Any
) -> None:
    db.execute(
        update(ImportAsset)
        .where(ImportAsset.import_task_id == task_id)
        .values(
            status="PENDING",
            file_id=None,
            error_code=None,
            error_summary=None,
            updated_at=updated_at,
        )
    )


def list_import_logs(
    db: Session,
    task_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    level: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[Any] = [ImportLog.import_task_id == task_id]
    if level:
        filters.append(ImportLog.level == level.lower())
    total = int(
        db.scalar(select(func.count()).select_from(ImportLog).where(*filters)) or 0
    )
    rows = (
        db.execute(
            select(ImportLog.__table__)
            .where(*filters)
            .order_by(ImportLog.created_at.desc(), ImportLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .mappings()
        .all()
    )
    logs = [dict(row) for row in rows]
    return logs, total


def list_libraries(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(select(Library.__table__).order_by(Library.created_at.desc()))
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_enabled_library_rows(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(Library.__table__)
            .where(Library.enabled.is_(True))
            .order_by(Library.created_at.desc(), Library.id.desc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_library_root_paths(db: Session) -> list[str]:
    return [
        str(path)
        for path in db.scalars(
            select(Library.root_path)
            .where(Library.root_path.is_not(None))
            .order_by(Library.created_at.desc(), Library.id.desc())
        ).all()
        if path
    ]


def list_import_source_paths_for_work(db: Session, work_id: str) -> list[str]:
    return [
        str(path)
        for path in db.scalars(
            select(ImportTask.source_path)
            .where(
                ImportTask.work_id == work_id,
                ImportTask.source_path.is_not(None),
            )
            .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
        ).all()
        if path
    ]


def import_status_snapshot(
    db: Session,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
    current_id = db.scalar(
        select(ImportTask.id)
        .where(ImportTask.status.in_(("PENDING", "PARSING")))
        .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
        .limit(1)
    )
    latest_id = db.scalar(
        select(ImportTask.id)
        .order_by(ImportTask.created_at.desc(), ImportTask.id.desc())
        .limit(1)
    )
    failed_count = int(
        db.scalar(
            select(func.count())
            .select_from(ImportTask)
            .where(ImportTask.status == "FAILED")
        )
        or 0
    )
    return (
        get_import_task(db, str(current_id)) if current_id else None,
        get_import_task(db, str(latest_id)) if latest_id else None,
        failed_count,
    )


def get_library(db: Session, library_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(select(Library.__table__).where(Library.id == library_id).limit(1))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def library_has_topology(db: Session, library_id: str) -> bool:
    return bool(db.scalar(select(exists().where(LibraryWork.library_id == library_id))))


def get_library_by_root_path(
    db: Session,
    root_path: str,
    *,
    exclude_id: str | None = None,
) -> dict[str, Any] | None:
    filters = [Library.root_path == root_path]
    if exclude_id is not None:
        filters.append(Library.id != exclude_id)
    row = (
        db.execute(select(Library.__table__).where(*filters).limit(1))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_library(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    prepared_values = {
        "id": str(values["id"]),
        "name": str(values["name"]),
        "rootPath": str(values["rootPath"]),
        "organizationMode": str(values["organizationMode"]),
        "enabled": bool(values.get("enabled", True)),
        "ignorePatterns": (
            str(values["ignorePatterns"])
            if values.get("ignorePatterns") is not None
            else None
        ),
        "ignoreHidden": bool(values.get("ignoreHidden", True)),
        "minFileSizeBytes": int(values.get("minFileSizeBytes", 10240)),
        "description": (
            str(values["description"])
            if values.get("description") is not None
            else None
        ),
        "createdAt": values["createdAt"],
        "updatedAt": values["updatedAt"],
    }
    db.execute(insert(Library.__table__).values(prepared_values))
    return get_library(db, str(prepared_values["id"])) or prepared_values


def update_library(
    db: Session, library_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    if db.get(Library, library_id) is None:
        return None
    mapping = {
        "name": "name",
        "rootPath": "root_path",
        "organizationMode": "organization_mode",
        "enabled": "enabled",
        "ignorePatterns": "ignore_patterns",
        "ignoreHidden": "ignore_hidden",
        "minFileSizeBytes": "min_file_size_bytes",
        "description": "description",
        "updatedAt": "updated_at",
    }
    prepared_values: dict[str, object] = {}
    for key, value in values.items():
        attribute = mapping.get(key)
        if attribute is not None:
            prepared_values[attribute] = value
    if prepared_values:
        db.execute(
            update(Library).where(Library.id == library_id).values(**prepared_values)
        )
    return get_library(db, library_id)


def reset_import_task_for_retry(
    db: Session,
    task_id: str,
    *,
    updated_at: Any,
) -> dict[str, Any] | None:
    if get_import_task(db, task_id) is None:
        return None
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == task_id)
        .values(
            status="PENDING",
            progress=0,
            processed_asset_count=0,
            message="已重新加入后台队列",
            error_code=None,
            error_summary=None,
            retryable=False,
            started_at=None,
            finished_at=None,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=updated_at,
        )
    )
    return get_import_task(db, task_id)


def delete_library(
    db: Session, folder_id: str, *, updated_at: Any
) -> tuple[bool, list[str]]:
    affected_user_ids = [
        str(item)
        for item in db.scalars(
            select(UserLibraryAccess.user_id).where(
                UserLibraryAccess.library_id == folder_id
            )
        ).all()
    ]
    result = db.execute(delete(Library).where(Library.id == folder_id))
    deleted = bool(result.rowcount)
    if deleted and affected_user_ids:
        db.execute(
            update(User)
            .where(User.id.in_(affected_user_ids))
            .values(
                authz_version=func.coalesce(User.authz_version, 1) + 1,
                updated_at=updated_at,
            )
        )
    return deleted, affected_user_ids


def list_library_access_user_ids(
    db: Session,
    folder_id: str,
) -> tuple[str, ...]:
    return tuple(
        str(user_id)
        for user_id in db.scalars(
            select(UserLibraryAccess.user_id).where(
                UserLibraryAccess.library_id == folder_id
            )
        ).all()
    )

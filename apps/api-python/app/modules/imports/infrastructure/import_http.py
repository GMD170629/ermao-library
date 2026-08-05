"""ORM helpers for import-task and monitor-folder HTTP adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    monitor_folder_visibility_predicate,
)
from app.models.auth import User, UserMonitorFolderAccess
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportLog,
    ImportTask,
)
from app.models.library import LibraryWork
from app.models.settings import MonitorFolder
from app.modules.imports.infrastructure.monitor import upsert_system_setting


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
    filters: list[Any] = [
        monitor_folder_visibility_predicate(context, ImportTask.monitor_folder_id)
    ]
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

    scope = monitor_folder_visibility_predicate(context, ImportTask.monitor_folder_id)
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
            db.scalar(select(func.count()).select_from(ImportTask).where(*filters))
            or 0
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
    monitor_folder_ids = {
        str(task["monitorFolderId"])
        for task in tasks
        if task.get("monitorFolderId")
    }
    work_ids = {str(task["workId"]) for task in tasks if task.get("workId")}

    monitor_folders = {
        str(row["id"]): dict(row)
        for row in db.execute(
            select(MonitorFolder.__table__).where(
                MonitorFolder.id.in_(monitor_folder_ids)
            )
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

    log_rank = func.row_number().over(
        partition_by=ImportLog.import_task_id,
        order_by=(ImportLog.created_at.desc(), ImportLog.id.desc()),
    ).label("page_rank")
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

    conversions = {
        str(row["importTaskId"]): dict(row)
        for row in db.execute(
            select(BookConversionTask.__table__).where(
                BookConversionTask.import_task_id.in_(task_ids)
            )
        )
        .mappings()
        .all()
    }

    return [
        {
            **task,
            "_pageMonitorFolder": monitor_folders.get(
                str(task.get("monitorFolderId") or "")
            ),
            "_pageWork": works.get(str(task.get("workId") or "")),
            "_pageLogs": logs_by_task_id[str(task["id"])],
            "_pageConversion": conversions.get(str(task["id"])),
        }
        for task in tasks
    ]


def clear_terminal_import_tasks(db: Session, context: AuthorizationContext) -> int:
    scope = monitor_folder_visibility_predicate(context, ImportTask.monitor_folder_id)
    terminal = select(ImportTask.id).where(
        ImportTask.status.in_(("COMPLETED", "FAILED")),
        scope,
    )
    db.execute(
        delete(BookConversionTask).where(
            BookConversionTask.import_task_id.in_(terminal)
        )
    )
    result = db.execute(
        delete(ImportTask).where(
            ImportTask.status.in_(("COMPLETED", "FAILED")),
            scope,
        )
    )
    return int(result.rowcount or 0)


def delete_import_task_row(db: Session, task_id: str) -> bool:
    db.execute(
        delete(BookConversionTask).where(BookConversionTask.import_task_id == task_id)
    )
    result = db.execute(delete(ImportTask).where(ImportTask.id == task_id))
    return bool(result.rowcount)


def get_conversion_for_import(db: Session, task_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(BookConversionTask.__table__)
            .where(BookConversionTask.import_task_id == task_id)
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


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


def request_monitor_rescan(db: Session, requested_value: str) -> None:
    """Persist rescan marker as a plain string (not JSON-encoded)."""
    upsert_system_setting(db, "monitor.rescanRequestedAt", requested_value)


def list_monitor_folders(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(MonitorFolder.__table__).order_by(MonitorFolder.created_at.desc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_enabled_monitor_folder_rows(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(MonitorFolder.__table__)
            .where(MonitorFolder.enabled.is_(True))
            .order_by(MonitorFolder.created_at.desc(), MonitorFolder.id.desc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_monitor_root_paths(db: Session) -> list[str]:
    return [
        str(path)
        for path in db.scalars(
            select(MonitorFolder.root_path)
            .where(MonitorFolder.root_path.is_not(None))
            .order_by(MonitorFolder.created_at.desc(), MonitorFolder.id.desc())
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


def get_monitor_folder(db: Session, folder_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(MonitorFolder.__table__)
            .where(MonitorFolder.id == folder_id)
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_monitor_folder_by_root_path(
    db: Session,
    root_path: str,
    *,
    exclude_id: str | None = None,
) -> dict[str, Any] | None:
    filters = [MonitorFolder.root_path == root_path]
    if exclude_id is not None:
        filters.append(MonitorFolder.id != exclude_id)
    row = (
        db.execute(select(MonitorFolder.__table__).where(*filters).limit(1))
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_monitor_folder(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    folder = MonitorFolder(
        id=str(values["id"]),
        name=str(values["name"]),
        root_path=str(values["rootPath"]),
        shelf_id=str(values["shelfId"]) if values.get("shelfId") is not None else None,
        enabled=bool(values.get("enabled", True)),
        media_kind_policy=str(values.get("mediaKindPolicy") or "MIXED"),
        ignore_patterns=str(values["ignorePatterns"])
        if values.get("ignorePatterns") is not None
        else None,
        ignore_hidden=bool(values.get("ignoreHidden", True)),
        min_file_size_bytes=int(values.get("minFileSizeBytes", 10240)),
        description=str(values["description"])
        if values.get("description") is not None
        else None,
        created_at=values["createdAt"],
        updated_at=values["updatedAt"],
    )
    db.add(folder)
    db.flush()
    return get_monitor_folder(db, folder.id) or dict(values)


def update_monitor_folder(
    db: Session, folder_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    folder = db.get(MonitorFolder, folder_id)
    if folder is None:
        return None
    mapping = {
        "name": "name",
        "rootPath": "root_path",
        "shelfId": "shelf_id",
        "enabled": "enabled",
        "mediaKindPolicy": "media_kind_policy",
        "ignorePatterns": "ignore_patterns",
        "ignoreHidden": "ignore_hidden",
        "minFileSizeBytes": "min_file_size_bytes",
        "description": "description",
        "updatedAt": "updated_at",
    }
    for key, value in values.items():
        attribute = mapping.get(key)
        if attribute is not None:
            setattr(folder, attribute, value)
    db.flush()
    return get_monitor_folder(db, folder.id)


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


def reset_conversion_for_retry(
    db: Session,
    task_id: str,
    *,
    updated_at: Any,
) -> dict[str, Any] | None:
    conversion = db.scalar(
        select(BookConversionTask).where(BookConversionTask.import_task_id == task_id)
    )
    if conversion is None:
        return None
    previous = get_conversion_for_import(db, task_id)
    conversion.status = "QUEUED"
    conversion.progress = 0
    conversion.retryable = False
    conversion.error_code = None
    conversion.error_summary = None
    conversion.started_at = None
    conversion.finished_at = None
    conversion.updated_at = updated_at
    db.flush()
    return previous


def delete_monitor_folder(
    db: Session, folder_id: str, *, updated_at: Any
) -> tuple[bool, list[str]]:
    affected_user_ids = [
        str(item)
        for item in db.scalars(
            select(UserMonitorFolderAccess.user_id).where(
                UserMonitorFolderAccess.monitor_folder_id == folder_id
            )
        ).all()
    ]
    result = db.execute(delete(MonitorFolder).where(MonitorFolder.id == folder_id))
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

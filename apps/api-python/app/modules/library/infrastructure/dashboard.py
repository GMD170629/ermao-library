"""ORM queries for dashboard and management overview surfaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    AuthorizationContext,
    edition_visibility_predicate,
    monitor_folder_visibility_predicate,
    work_visibility_predicate,
)
from app.core.time import to_timestamp_ms
from app.models.import_pipeline import DownloadTask, ImportTask
from app.models.library import LibraryEdition, LibraryFile, LibraryReadingProgress, LibraryWork
from app.models.settings import MonitorFolder, SystemEvent
from app.modules.imports.infrastructure.schema import entity_as_legacy_dict, has_table, reflected_table


def dashboard_summary(db: Session, context: AuthorizationContext, user_id: str) -> dict[str, Any]:
    work_visible = work_visibility_predicate(context)
    total_books = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(LibraryWork.hidden.is_(False), work_visible)
        )
        or 0
    ) if has_table(db, "LibraryWork") else 0
    comic_books = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(
                LibraryWork.hidden.is_(False),
                LibraryWork.work_type == "COMIC",
                work_visible,
            )
        )
        or 0
    ) if has_table(db, "LibraryWork") else 0
    novel_books = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(
                LibraryWork.hidden.is_(False),
                LibraryWork.work_type == "EPUB",
                work_visible,
            )
        )
        or 0
    ) if has_table(db, "LibraryWork") else 0

    storage = 0
    if has_table(db, "LibraryEdition"):
        storage = int(
            db.scalar(
                select(func.coalesce(func.sum(LibraryEdition.size_bytes), 0)).where(
                    LibraryEdition.hidden.is_(False),
                    edition_visibility_predicate(context),
                )
            )
            or 0
        )

    last_import: dict[str, Any] | None = None
    if has_table(db, "ImportTask"):
        row = db.execute(
            select(ImportTask.finished_at, ImportTask.updated_at)
            .where(
                ImportTask.status == "COMPLETED",
                monitor_folder_visibility_predicate(context, ImportTask.monitor_folder_id),
            )
            .order_by(ImportTask.finished_at.desc(), ImportTask.id.desc())
            .limit(1)
        ).first()
        if row is not None:
            last_import = {"finishedAt": row.finished_at, "updatedAt": row.updated_at}

    latest_progress_at = None
    if has_table(db, "LibraryReadingProgress"):
        latest_progress_at = db.scalar(
            select(LibraryReadingProgress.updated_at)
            .where(LibraryReadingProgress.user_id == user_id)
            .order_by(LibraryReadingProgress.updated_at.desc())
            .limit(1)
        )

    monitor_folder_count = (
        int(
            db.scalar(
                select(func.count()).select_from(MonitorFolder).where(MonitorFolder.enabled.is_(True))
            )
            or 0
        )
        if context.is_admin and has_table(db, "MonitorFolder")
        else len(context.monitor_folder_ids)
    )

    return {
        "totalBooks": total_books,
        "comicBooks": comic_books,
        "novelBooks": novel_books,
        "storageUsedBytes": storage,
        "monitorFolderCount": monitor_folder_count,
        "lastImportAt": (last_import or {}).get("finishedAt") or (last_import or {}).get("updatedAt"),
        "latestSyncAt": latest_progress_at,
    }


def recent_books(db: Session, context: AuthorizationContext, *, limit: int) -> list[dict[str, Any]]:
    if not has_table(db, "LibraryWork"):
        return []
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.cover_status,
            LibraryWork.cover_path,
            LibraryWork.created_at,
        )
        .where(LibraryWork.hidden.is_(False), work_visibility_predicate(context))
        .order_by(LibraryWork.created_at.desc(), LibraryWork.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "coverStatus": row.cover_status,
            "coverPath": row.cover_path,
            "createdAt": row.created_at,
        }
        for row in rows
    ]


def recent_reading(db: Session, context: AuthorizationContext, user_id: str, *, limit: int) -> list[dict[str, Any]]:
    if not all(has_table(db, name) for name in ("LibraryWork", "LibraryEdition", "LibraryReadingProgress")):
        return []
    recent_edition = aliased(LibraryEdition)
    latest_read_at = func.max(LibraryReadingProgress.updated_at).label("lastReadAt")
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.cover_status,
            LibraryWork.cover_path,
            latest_read_at,
        )
        .join(LibraryReadingProgress, LibraryReadingProgress.work_id == LibraryWork.id)
        .join(recent_edition, recent_edition.id == LibraryReadingProgress.edition_id)
        .where(
            LibraryReadingProgress.user_id == user_id,
            LibraryWork.hidden.is_(False),
            func.coalesce(recent_edition.hidden, False).is_(False),
            work_visibility_predicate(context),
            edition_visibility_predicate(context, recent_edition),
        )
        .group_by(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.cover_status,
            LibraryWork.cover_path,
        )
        .order_by(latest_read_at.desc(), LibraryWork.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "coverStatus": row.cover_status,
            "coverPath": row.cover_path,
            "lastReadAt": row.lastReadAt,
        }
        for row in rows
    ]


def continue_reading_progress(
    db: Session, context: AuthorizationContext, user_id: str
) -> dict[str, Any] | None:
    if not all(has_table(db, name) for name in ("LibraryReadingProgress", "LibraryWork", "LibraryEdition")):
        return None
    progress = reflected_table(db, "LibraryReadingProgress")
    work = reflected_table(db, "LibraryWork")
    edition = reflected_table(db, "LibraryEdition")
    filters = [
        progress.c.userId == user_id,
        progress.c.percent > 0,
        progress.c.percent < 100,
        work.c.hidden.is_(False),
        func.coalesce(edition.c.hidden, False).is_(False),
    ]
    if not context.is_admin and "monitorFolderId" in edition.c:
        filters.append(monitor_folder_visibility_predicate(context, edition.c.monitorFolderId))
    row = db.execute(
        select(progress)
        .select_from(
            progress.join(work, work.c.id == progress.c.workId).join(
                edition, edition.c.id == progress.c.editionId
            )
        )
        .where(*filters)
        .order_by(progress.c.updatedAt.desc())
        .limit(1)
    ).mappings().first()
    return dict(row) if row else None


def management_card_counts(db: Session) -> dict[str, int]:
    failed_imports = (
        int(db.scalar(select(func.count()).select_from(ImportTask).where(ImportTask.status == "FAILED")) or 0)
        if has_table(db, "ImportTask")
        else 0
    )
    failed_downloads = (
        int(db.scalar(select(func.count()).select_from(DownloadTask).where(DownloadTask.status == "failed")) or 0)
        if has_table(db, "DownloadTask")
        else 0
    )
    pending_organize = (
        int(
            db.scalar(
                select(func.count())
                .select_from(LibraryWork)
                .where(
                    LibraryWork.hidden.is_(False),
                    LibraryWork.organize_status.in_(("PENDING", "REVIEWING")),
                )
            )
            or 0
        )
        if has_table(db, "LibraryWork")
        else 0
    )
    storage = (
        int(db.scalar(select(func.coalesce(func.sum(LibraryFile.size_bytes), 0))) or 0)
        if has_table(db, "LibraryFile")
        else 0
    )
    return {
        "failedImports": failed_imports,
        "failedDownloads": failed_downloads,
        "pendingOrganize": pending_organize,
        "managedStorageBytes": storage,
    }


def list_library_file_paths(db: Session) -> set[str]:
    if not has_table(db, "LibraryFile"):
        return set()
    return {
        str(path)
        for path in db.scalars(select(LibraryFile.path).where(LibraryFile.path.is_not(None))).all()
        if path
    }


def list_management_works(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    if not has_table(db, "LibraryWork"):
        return []
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.series_name,
            LibraryWork.work_type,
            LibraryWork.monitor_folder_id,
            LibraryWork.organize_status,
            LibraryWork.hidden,
            LibraryWork.updated_at,
        )
        .where(LibraryWork.hidden.is_(False))
        .order_by(LibraryWork.updated_at.desc(), LibraryWork.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "seriesName": row.series_name,
            "workType": row.work_type,
            "monitorFolderId": row.monitor_folder_id,
            "organizeStatus": row.organize_status,
            "hidden": row.hidden,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def list_management_file_rows(
    db: Session,
    *,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    if not has_table(db, "LibraryFile"):
        return []
    rows = db.execute(
        select(LibraryFile.path, LibraryFile.size_bytes)
        .order_by(LibraryFile.path.asc(), LibraryFile.id.asc())
        .limit(limit)
    ).all()
    return [
        {"path": row.path, "sizeBytes": int(row.size_bytes or 0)}
        for row in rows
    ]


def recent_system_events(db: Session, *, limit: int = 8) -> list[dict[str, Any]]:
    if not has_table(db, "SystemEvent"):
        return []
    rows = db.scalars(select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)).all()
    return [entity_as_legacy_dict(row) for row in rows]


def list_system_events_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    level: str | None = None,
    source: str | None = None,
    target_type: str | None = None,
    search: str | None = None,
    date_from_ms: int | None = None,
    date_to_ms: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if not has_table(db, "SystemEvent"):
        return [], 0
    filters: list[Any] = []
    if level:
        filters.append(SystemEvent.level == ("warning" if level == "warn" else level))
    if source:
        filters.append(SystemEvent.source == source)
    if target_type:
        filters.append(SystemEvent.target_type == target_type)
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            SystemEvent.message.like(term)
            | SystemEvent.action.like(term)
            | func.coalesce(SystemEvent.target_id, "").like(term)
        )
    rows = list(
        db.scalars(
            select(SystemEvent)
            .where(*filters)
            .order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc())
        ).all()
    )
    if date_from_ms is not None or date_to_ms is not None:
        filtered: list[SystemEvent] = []
        for row in rows:
            created_ms = to_timestamp_ms(row.created_at)
            if created_ms is None:
                continue
            if date_from_ms is not None and created_ms < date_from_ms:
                continue
            if date_to_ms is not None and created_ms >= date_to_ms:
                continue
            filtered.append(row)
        rows = filtered
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    page_rows = rows[(page - 1) * page_size : page * page_size]
    return [entity_as_legacy_dict(row) for row in page_rows], total


def clear_info_warning_events(db: Session) -> int:
    if not has_table(db, "SystemEvent"):
        return 0
    from sqlalchemy import delete

    result = db.execute(delete(SystemEvent).where(SystemEvent.level.in_(("info", "warning"))))
    return int(result.rowcount or 0)

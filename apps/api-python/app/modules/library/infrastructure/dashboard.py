"""ORM queries for dashboard and management overview surfaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import reader_type_for_format
from app.core.authorization import (
    AuthorizationContext,
    monitor_folder_visibility_predicate,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.core.time import to_timestamp_ms
from app.models.import_pipeline import DownloadTask, ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.settings import MonitorFolder, SystemEvent
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.modules.reader.public import (
    MediaKind,
    VolumeReadingState,
    choose_continue_volume_id,
)


def dashboard_summary(
    db: Session, context: AuthorizationContext, user_id: str
) -> dict[str, Any]:
    work_visible = work_visibility_predicate(context)
    total_books = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(LibraryWork.hidden.is_(False), work_visible)
        )
        or 0
    )

    def media_kind_work_count(media_kind: MediaKind) -> int:
        return int(
            db.scalar(
                select(func.count(func.distinct(LibraryWork.id)))
                .select_from(LibraryWork)
                .join(
                    LibraryMediaVersion,
                    LibraryMediaVersion.work_id == LibraryWork.id,
                )
                .where(
                    LibraryWork.hidden.is_(False),
                    LibraryMediaVersion.media_kind == media_kind.value,
                    work_visible,
                )
            )
            or 0
        )

    ebook_books = media_kind_work_count(MediaKind.EBOOK)
    comic_books = media_kind_work_count(MediaKind.COMIC)
    audiobook_books = media_kind_work_count(MediaKind.AUDIOBOOK)

    storage = int(
        db.scalar(
            select(func.coalesce(func.sum(LibraryVolume.size_bytes), 0)).where(
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(context),
            )
        )
        or 0
    )

    last_import: dict[str, Any] | None = None
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

    latest_progress_at = db.scalar(
        select(LibraryReadingProgress.updated_at)
        .where(LibraryReadingProgress.user_id == user_id)
        .order_by(LibraryReadingProgress.updated_at.desc())
        .limit(1)
    )

    monitor_folder_count = (
        int(
            db.scalar(
                select(func.count())
                .select_from(MonitorFolder)
                .where(MonitorFolder.enabled.is_(True))
            )
            or 0
        )
        if context.is_admin
        else len(context.monitor_folder_ids)
    )

    return {
        "totalBooks": total_books,
        "ebookBooks": ebook_books,
        "comicBooks": comic_books,
        "audiobookBooks": audiobook_books,
        "storageUsedBytes": storage,
        "monitorFolderCount": monitor_folder_count,
        "lastImportAt": (last_import or {}).get("finishedAt")
        or (last_import or {}).get("updatedAt"),
        "latestSyncAt": latest_progress_at,
    }


def recent_books(
    db: Session, context: AuthorizationContext, *, limit: int
) -> list[dict[str, Any]]:
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


def recent_reading(
    db: Session, context: AuthorizationContext, user_id: str, *, limit: int
) -> list[dict[str, Any]]:
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
        .join(LibraryMediaVersion, LibraryMediaVersion.work_id == LibraryWork.id)
        .join(LibraryVolume, LibraryVolume.media_version_id == LibraryMediaVersion.id)
        .join(
            LibraryReadingProgress, LibraryReadingProgress.volume_id == LibraryVolume.id
        )
        .where(
            LibraryReadingProgress.user_id == user_id,
            LibraryWork.hidden.is_(False),
            LibraryVolume.hidden.is_(False),
            work_visibility_predicate(context),
            volume_visibility_predicate(context),
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
    rows = db.execute(
        select(
            LibraryVolume.id.label("volume_id"),
            LibraryVolume.media_version_id,
            LibraryVolume.title.label("volume_title"),
            LibraryVolume.sort_order,
            LibraryVolume.narrator,
            LibraryVolume.format.label("volume_format"),
            LibraryMediaVersion.media_kind,
            LibraryWork.id.label("work_id"),
            LibraryWork.title.label("work_title"),
            LibraryWork.author,
            LibraryWork.cover_path,
            LibraryWork.cover_status,
            LibraryReadingProgress.percent,
            LibraryReadingProgress.updated_at.label("progress_updated_at"),
            UserMediaHistory.last_volume_id,
            UserMediaHistory.updated_at.label("history_updated_at"),
        )
        .select_from(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .join(LibraryWork, LibraryWork.id == LibraryMediaVersion.work_id)
        .outerjoin(
            LibraryReadingProgress,
            (LibraryReadingProgress.volume_id == LibraryVolume.id)
            & (LibraryReadingProgress.user_id == user_id),
        )
        .outerjoin(
            UserMediaHistory,
            (UserMediaHistory.media_version_id == LibraryMediaVersion.id)
            & (UserMediaHistory.user_id == user_id),
        )
        .where(
            LibraryWork.hidden.is_(False),
            LibraryVolume.hidden.is_(False),
            volume_visibility_predicate(context),
        )
        .order_by(
            LibraryMediaVersion.id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    if not rows:
        return None

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row.media_version_id), []).append(row)

    unfinished_media = [
        media_version_id
        for media_version_id, media_rows in grouped.items()
        if any(float(row.percent or 0) < 100 for row in media_rows)
    ]
    candidate_media = unfinished_media or list(grouped)
    media_priority = {
        MediaKind.EBOOK: 0,
        MediaKind.COMIC: 1,
        MediaKind.AUDIOBOOK: 2,
    }

    def media_rank(media_version_id: str) -> tuple[float, int, str, str]:
        media_rows = grouped[media_version_id]
        recent_at = max(
            (
                row.history_updated_at or row.progress_updated_at
                for row in media_rows
                if row.history_updated_at is not None
                or row.progress_updated_at is not None
            ),
            default=None,
        )
        kind = MediaKind(str(media_rows[0].media_kind))
        return (
            -(recent_at.timestamp() if recent_at is not None else float("-inf")),
            media_priority[kind],
            str(media_rows[0].work_id),
            media_version_id,
        )

    selected_media_id = min(candidate_media, key=media_rank)
    selected_media_rows = grouped[selected_media_id]
    states = [
        VolumeReadingState(
            volume_id=str(row.volume_id),
            media_kind=MediaKind(str(row.media_kind)),
            sort_order=int(row.sort_order),
            percent=int(float(row.percent or 0)),
            last_read_at=(
                row.history_updated_at
                if row.last_volume_id == row.volume_id
                else row.progress_updated_at
            ),
        )
        for row in selected_media_rows
    ]
    selected_volume_id = choose_continue_volume_id(states)
    if selected_volume_id is None:
        return None
    selected = next(
        row for row in selected_media_rows if row.volume_id == selected_volume_id
    )
    reader_type = reader_type_for_format(str(selected.volume_format))
    return {
        "workId": selected.work_id,
        "title": selected.work_title,
        "author": selected.author,
        "coverPath": selected.cover_path,
        "coverStatus": selected.cover_status,
        "mediaKind": selected.media_kind,
        "volumeFormat": selected.volume_format,
        "readerType": reader_type.value if reader_type else "reflowable",
        "volumeId": selected.volume_id,
        "volumeTitle": selected.volume_title,
        "narrator": selected.narrator,
        "percent": float(selected.percent or 0),
        "updatedAt": selected.progress_updated_at,
    }


def management_card_counts(db: Session) -> dict[str, int]:
    failed_imports = int(
        db.scalar(
            select(func.count())
            .select_from(ImportTask)
            .where(ImportTask.status == "FAILED")
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
            .select_from(LibraryWork)
            .where(
                LibraryWork.hidden.is_(False),
                LibraryWork.organize_status.in_(("PENDING", "REVIEWING")),
            )
        )
        or 0
    )
    storage = int(
        db.scalar(select(func.coalesce(func.sum(LibraryFile.size_bytes), 0))) or 0
    )
    return {
        "failedImports": failed_imports,
        "failedDownloads": failed_downloads,
        "pendingOrganize": pending_organize,
        "managedStorageBytes": storage,
    }


def list_library_file_paths(db: Session) -> set[str]:
    return {
        str(path)
        for path in db.scalars(
            select(LibraryFile.path).where(LibraryFile.path.is_not(None))
        ).all()
        if path
    }


def list_management_works(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.series_name,
            LibraryWork.monitor_folder_id,
            LibraryWork.organize_status,
            LibraryWork.hidden,
            LibraryWork.updated_at,
        )
        .where(LibraryWork.hidden.is_(False))
        .order_by(LibraryWork.updated_at.desc(), LibraryWork.id.desc())
        .limit(limit)
    ).all()
    work_ids = [str(row.id) for row in rows]
    kinds_by_work: dict[str, list[str]] = {work_id: [] for work_id in work_ids}
    if work_ids:
        media_rows = db.execute(
            select(LibraryMediaVersion.work_id, LibraryMediaVersion.media_kind)
            .where(LibraryMediaVersion.work_id.in_(work_ids))
            .order_by(
                LibraryMediaVersion.work_id.asc(),
                LibraryMediaVersion.id.asc(),
            )
        ).all()
        priority = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}
        for work_id, media_kind in media_rows:
            kinds_by_work[str(work_id)].append(str(media_kind))
        for media_kinds in kinds_by_work.values():
            media_kinds.sort(key=lambda kind: (priority.get(kind, 3), kind))
    return [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "seriesName": row.series_name,
            "availableMediaKinds": kinds_by_work[str(row.id)],
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
    rows = db.execute(
        select(LibraryFile.path, LibraryFile.size_bytes)
        .order_by(LibraryFile.path.asc(), LibraryFile.id.asc())
        .limit(limit)
    ).all()
    return [{"path": row.path, "sizeBytes": int(row.size_bytes or 0)} for row in rows]


def recent_system_events(db: Session, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)
    ).all()
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
    from sqlalchemy import delete

    result = db.execute(
        delete(SystemEvent).where(SystemEvent.level.in_(("info", "warning")))
    )
    return int(result.rowcount or 0)

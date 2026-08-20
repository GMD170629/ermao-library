"""ORM queries for dashboard and management overview surfaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import reader_type_for_format
from app.core.authorization import (
    AuthorizationContext,
    library_visibility_predicate,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.import_pipeline import DownloadTask, ImportTask
from app.models.library import (
    Library,
    LibraryFile,
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import SystemEvent
from app.modules.library.infrastructure.media_kind_sql import (
    volume_effective_media_kind,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.modules.reader.public import MediaKind


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
        volume_media_kind = volume_effective_media_kind(LibraryVolume)
        return int(
            db.scalar(
                select(func.count(func.distinct(LibraryWork.id)))
                .select_from(LibraryWork)
                .join(
                    LibraryVersion,
                    LibraryVersion.work_id == LibraryWork.id,
                )
                .join(
                    LibraryVolume,
                    LibraryVolume.version_id == LibraryVersion.id,
                )
                .where(
                    LibraryWork.hidden.is_(False),
                    LibraryVolume.hidden.is_(False),
                    volume_media_kind == media_kind.value,
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
            library_visibility_predicate(context, ImportTask.library_id),
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

    library_count = (
        int(
            db.scalar(
                select(func.count())
                .select_from(Library)
                .where(Library.enabled.is_(True))
            )
            or 0
        )
        if context.is_admin
        else len(context.library_ids)
    )

    return {
        "totalBooks": total_books,
        "ebookBooks": ebook_books,
        "comicBooks": comic_books,
        "audiobookBooks": audiobook_books,
        "storageUsedBytes": storage,
        "libraryCount": library_count,
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
        .join(LibraryVersion, LibraryVersion.work_id == LibraryWork.id)
        .join(LibraryVolume, LibraryVolume.version_id == LibraryVersion.id)
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
    volume_kind = volume_effective_media_kind(LibraryVolume)

    def latest_progress(*, unfinished_only: bool):
        statement = (
            select(
                LibraryVolume.id.label("volume_id"),
                LibraryVolume.title.label("volume_title"),
                LibraryVolume.narrator,
                LibraryVolume.format.label("volume_format"),
                volume_kind.label("media_kind"),
                LibraryWork.id.label("work_id"),
                LibraryWork.title.label("work_title"),
                LibraryWork.author,
                LibraryWork.cover_path,
                LibraryWork.cover_status,
                LibraryWork.updated_at.label("work_updated_at"),
                LibraryReadingProgress.percent,
                LibraryReadingProgress.updated_at.label("progress_updated_at"),
            )
            .select_from(LibraryReadingProgress)
            .join(
                LibraryVolume,
                LibraryVolume.id == LibraryReadingProgress.volume_id,
            )
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
            .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
            .where(
                LibraryReadingProgress.user_id == user_id,
                LibraryWork.hidden.is_(False),
                LibraryVolume.hidden.is_(False),
                work_visibility_predicate(context),
                volume_visibility_predicate(context),
            )
            .order_by(
                LibraryReadingProgress.updated_at.desc(),
                LibraryReadingProgress.id.desc(),
            )
            .limit(1)
        )
        if unfinished_only:
            statement = statement.where(
                func.coalesce(LibraryReadingProgress.percent, 0) < 100
            )
        return db.execute(statement).first()

    selected = latest_progress(unfinished_only=True) or latest_progress(
        unfinished_only=False
    )
    if selected is None:
        return None
    reader_type = reader_type_for_format(str(selected.volume_format))
    return {
        "workId": selected.work_id,
        "title": selected.work_title,
        "author": selected.author,
        "coverPath": selected.cover_path,
        "coverStatus": selected.cover_status,
        "workUpdatedAt": selected.work_updated_at,
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


def list_management_works(db: Session, *, limit: int = 300) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.series_name,
            LibraryWork.library_id,
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
        media_kind = volume_effective_media_kind(LibraryVolume)
        media_rows = db.execute(
            select(
                LibraryVersion.work_id,
                media_kind.label("media_kind"),
            )
            .select_from(LibraryVolume)
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
            .where(
                LibraryVersion.work_id.in_(work_ids),
                LibraryVolume.hidden.is_(False),
            )
            .group_by(LibraryVersion.work_id, media_kind)
            .order_by(
                LibraryVersion.work_id.asc(),
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
            "libraryId": row.library_id,
            "organizeStatus": row.organize_status,
            "hidden": row.hidden,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def recent_system_events(db: Session, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]

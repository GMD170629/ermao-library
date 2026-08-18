"""ORM queries for dashboard and management overview surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.contracts.media_capabilities import reader_type_for_format
from app.core.authorization import (
    AuthorizationContext,
    library_visibility_predicate,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.import_pipeline import DownloadTask, ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.library import Library
from app.models.settings import SystemEvent
from app.modules.library.infrastructure.works import entity_as_legacy_dict
from app.modules.reader.public import (
    MediaKind,
    VolumeReadingState,
    choose_continue_volume_id,
)


@dataclass(frozen=True, slots=True)
class _MediaActivityCandidate:
    media_version_id: str
    recent_at: datetime
    media_kind: MediaKind
    work_id: str


def _media_priority(column: ColumnElement[str]) -> ColumnElement[int]:
    return case(
        (column == MediaKind.EBOOK.value, 0),
        (column == MediaKind.COMIC.value, 1),
        (column == MediaKind.AUDIOBOOK.value, 2),
        else_=3,
    )


def _visible_media_volume_exists(
    context: AuthorizationContext,
    user_id: str,
    media_version_id: ColumnElement[str],
    *,
    unfinished_only: bool,
) -> ColumnElement[bool]:
    volume = aliased(LibraryVolume)
    progress = aliased(LibraryReadingProgress)
    statement = (
        select(volume.id)
        .outerjoin(
            progress,
            (progress.volume_id == volume.id) & (progress.user_id == user_id),
        )
        .where(
            volume.version_id == media_version_id,
            volume.hidden.is_(False),
            volume_visibility_predicate(context, volume),
        )
    )
    if unfinished_only:
        statement = statement.where(func.coalesce(progress.percent, 0) < 100)
    return exists(statement)


def _history_activity_candidate(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    unfinished_only: bool,
) -> _MediaActivityCandidate | None:
    row = db.execute(
        select(
            UserMediaHistory.media_version_id,
            UserMediaHistory.updated_at.label("recent_at"),
            LibraryMediaVersion.media_kind,
            LibraryWork.id.label("work_id"),
        )
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == UserMediaHistory.media_version_id,
        )
        .join(LibraryWork, LibraryWork.id == LibraryMediaVersion.work_id)
        .where(
            UserMediaHistory.user_id == user_id,
            LibraryWork.hidden.is_(False),
            _visible_media_volume_exists(
                context,
                user_id,
                LibraryMediaVersion.id,
                unfinished_only=unfinished_only,
            ),
        )
        .order_by(
            UserMediaHistory.updated_at.desc(),
            _media_priority(LibraryMediaVersion.media_kind),
            LibraryWork.id.asc(),
            LibraryMediaVersion.id.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return _MediaActivityCandidate(
        media_version_id=str(row.media_version_id),
        recent_at=row.recent_at,
        media_kind=MediaKind(str(row.media_kind)),
        work_id=str(row.work_id),
    )


def _progress_activity_candidate(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    unfinished_only: bool,
) -> _MediaActivityCandidate | None:
    history = aliased(UserMediaHistory)
    row = db.execute(
        select(
            LibraryVolume.version_id.label("media_version_id"),
            LibraryReadingProgress.updated_at.label("recent_at"),
            LibraryVersion.source_key.label("media_kind"),
            LibraryWork.id.label("work_id"),
        )
        .join(
            LibraryVolume,
            LibraryVolume.id == LibraryReadingProgress.volume_id,
        )
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
        .where(
            LibraryReadingProgress.user_id == user_id,
            LibraryWork.hidden.is_(False),
            LibraryVolume.hidden.is_(False),
            volume_visibility_predicate(context),
            ~exists(
                select(history.id).where(
                    history.user_id == user_id,
                    history.media_version_id == LibraryVersion.id,
                )
            ),
            _visible_media_volume_exists(
                context,
                user_id,
                LibraryVersion.id,
                unfinished_only=unfinished_only,
            ),
        )
        .order_by(
            LibraryReadingProgress.updated_at.desc(),
            _media_priority(LibraryVersion.source_key),
            LibraryWork.id.asc(),
            LibraryVersion.id.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return _MediaActivityCandidate(
        media_version_id=str(row.media_version_id),
        recent_at=row.recent_at,
        media_kind=MediaKind(str(row.media_kind)),
        work_id=str(row.work_id),
    )


def _candidate_rank(candidate: _MediaActivityCandidate) -> tuple[float, int, str, str]:
    media_priority = {
        MediaKind.EBOOK: 0,
        MediaKind.COMIC: 1,
        MediaKind.AUDIOBOOK: 2,
    }
    return (
        -candidate.recent_at.timestamp(),
        media_priority[candidate.media_kind],
        candidate.work_id,
        candidate.media_version_id,
    )


def _recent_activity_media_id(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    unfinished_only: bool,
) -> str | None:
    candidates = [
        candidate
        for candidate in (
            _history_activity_candidate(
                db,
                context,
                user_id,
                unfinished_only=unfinished_only,
            ),
            _progress_activity_candidate(
                db,
                context,
                user_id,
                unfinished_only=unfinished_only,
            ),
        )
        if candidate is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=_candidate_rank).media_version_id


def _first_visible_media_id(
    db: Session,
    context: AuthorizationContext,
    user_id: str,
    *,
    unfinished_only: bool,
) -> str | None:
    return db.scalar(
        select(LibraryVersion.id)
        .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
        .where(
            LibraryWork.hidden.is_(False),
            _visible_media_volume_exists(
                context,
                user_id,
                LibraryVersion.id,
                unfinished_only=unfinished_only,
            ),
        )
        .order_by(
            _media_priority(LibraryVersion.source_key),
            LibraryWork.id.asc(),
            LibraryVersion.id.asc(),
        )
        .limit(1)
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
    selected_media_id = _recent_activity_media_id(
        db,
        context,
        user_id,
        unfinished_only=True,
    ) or _first_visible_media_id(
        db,
        context,
        user_id,
        unfinished_only=True,
    )
    if selected_media_id is None:
        selected_media_id = _recent_activity_media_id(
            db,
            context,
            user_id,
            unfinished_only=False,
        ) or _first_visible_media_id(
            db,
            context,
            user_id,
            unfinished_only=False,
        )
    if selected_media_id is None:
        return None

    rows = db.execute(
        select(
            LibraryVolume.id.label("volume_id"),
            LibraryVolume.version_id,
            LibraryVolume.title.label("volume_title"),
            LibraryVolume.sort_order,
            LibraryVolume.narrator,
            LibraryVolume.format.label("volume_format"),
            LibraryVersion.source_key.label("media_kind"),
            LibraryWork.id.label("work_id"),
            LibraryWork.title.label("work_title"),
            LibraryWork.author,
            LibraryWork.cover_path,
            LibraryWork.cover_status,
            LibraryWork.updated_at.label("work_updated_at"),
            LibraryReadingProgress.percent,
            LibraryReadingProgress.updated_at.label("progress_updated_at"),
            UserMediaHistory.last_volume_id,
            UserMediaHistory.updated_at.label("history_updated_at"),
        )
        .select_from(LibraryVolume)
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
        .outerjoin(
            LibraryReadingProgress,
            (LibraryReadingProgress.volume_id == LibraryVolume.id)
            & (LibraryReadingProgress.user_id == user_id),
        )
        .outerjoin(
            UserMediaHistory,
            (UserMediaHistory.media_version_id == LibraryVersion.id)
            & (UserMediaHistory.user_id == user_id),
        )
        .where(
            LibraryVersion.id == selected_media_id,
            LibraryWork.hidden.is_(False),
            LibraryVolume.hidden.is_(False),
            volume_visibility_predicate(context),
        )
        .order_by(
            LibraryVersion.id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    if not rows:
        return None
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
        for row in rows
    ]
    selected_volume_id = choose_continue_volume_id(states)
    if selected_volume_id is None:
        return None
    selected = next(row for row in rows if row.volume_id == selected_volume_id)
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
            "libraryId": row.library_id,
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

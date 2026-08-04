"""ORM queries for import worker library and task side effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Integer, case, cast, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import (
    BookConversionTask,
    DownloadTask,
    ImportAsset,
    ImportTask,
)
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.settings import MonitorFolder
from app.models.shelf import Shelf, ShelfWork


def _records(
    db: Session,
    statement: Any,
) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(statement).mappings().all()]


def _first_record(db: Session, statement: Any) -> dict[str, Any] | None:
    row = db.execute(statement.limit(1)).mappings().first()
    return dict(row) if row else None


def _list_library_files(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(LibraryFile.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def _list_reading_units(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(LibraryReadingUnit.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def list_reflowable_chapters_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _list_reading_units(
        db,
        LibraryReadingUnit.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
        func.lower(LibraryReadingUnit.unit_type) == "chapter",
        order_by=(LibraryReadingUnit.sort_order, LibraryReadingUnit.id),
    )


def list_reflowable_chapters_for_volume(
    db: Session, volume_id: str
) -> list[dict[str, Any]]:
    return _list_reading_units(
        db,
        LibraryReadingUnit.volume_id == volume_id,
        func.lower(LibraryReadingUnit.unit_type) == "chapter",
        order_by=(LibraryReadingUnit.sort_order, LibraryReadingUnit.id),
    )


def _list_reading_progress(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(LibraryReadingProgress.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def _list_consumption_states(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(UserMediaHistory.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def _list_media_versions(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(LibraryMediaVersion.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def _list_volumes(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(LibraryVolume.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    if limit is not None:
        statement = statement.limit(limit)
    return _records(db, statement)


def _get_import_task(
    db: Session, *filters: Any, order_by: tuple[Any, ...] | None = None
) -> dict[str, Any] | None:
    statement = select(ImportTask.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    return _first_record(db, statement)


def _get_import_asset(db: Session, *filters: Any) -> dict[str, Any] | None:
    return _first_record(db, select(ImportAsset.__table__).where(*filters))


def _get_conversion(db: Session, *filters: Any) -> dict[str, Any] | None:
    return _first_record(db, select(BookConversionTask.__table__).where(*filters))


def _get_work(db: Session, *filters: Any) -> dict[str, Any] | None:
    return _first_record(db, select(LibraryWork.__table__).where(*filters))


def _get_media_version(
    db: Session, *filters: Any, order_by: tuple[Any, ...] | None = None
) -> dict[str, Any] | None:
    statement = select(LibraryMediaVersion.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    return _first_record(db, statement)


def _get_volume(
    db: Session, *filters: Any, order_by: tuple[Any, ...] | None = None
) -> dict[str, Any] | None:
    statement = select(LibraryVolume.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    return _first_record(db, statement)


def _get_organize_job(db: Session, *filters: Any) -> dict[str, Any] | None:
    return _first_record(db, select(OrganizeJob.__table__).where(*filters))


def _count_media_versions(db: Session, *filters: Any) -> int:
    return int(
        db.scalar(select(func.count()).select_from(LibraryMediaVersion).where(*filters))
        or 0
    )


def _count_files(db: Session, *filters: Any) -> int:
    return int(
        db.scalar(select(func.count()).select_from(LibraryFile).where(*filters)) or 0
    )


def _count_reading_units(db: Session, *filters: Any) -> int:
    return int(
        db.scalar(select(func.count()).select_from(LibraryReadingUnit).where(*filters))
        or 0
    )


def _count_volumes(db: Session, *filters: Any) -> int:
    return int(
        db.scalar(select(func.count()).select_from(LibraryVolume).where(*filters)) or 0
    )


def _scalar_value(db: Session, statement: Any, default: Any = None) -> Any:
    value = db.scalar(statement)
    return default if value is None else value


def get_conversion_by_import_task_id(
    db: Session, import_task_id: str
) -> dict[str, Any] | None:
    return _get_conversion(db, BookConversionTask.import_task_id == import_task_id)


def get_import_task_by_id(db: Session, task_id: str) -> dict[str, Any] | None:
    return _get_import_task(db, ImportTask.id == task_id)


def get_work_by_id(db: Session, work_id: str) -> dict[str, Any] | None:
    return _get_work(db, LibraryWork.id == work_id)


def get_work_by_merge_key(db: Session, merge_key: str) -> dict[str, Any] | None:
    return _get_work(db, LibraryWork.merge_key == merge_key)


def list_works_by_merge_key_prefix(
    db: Session, merge_key_prefix: str
) -> list[dict[str, Any]]:
    """List deterministic fuzzy-merge candidates within one source directory."""

    return _records(
        db,
        select(LibraryWork.__table__)
        .where(LibraryWork.merge_key.startswith(merge_key_prefix, autoescape=True))
        .order_by(LibraryWork.created_at.asc(), LibraryWork.id.asc()),
    )


def list_works_by_normalized_identity(
    db: Session,
    normalized_title: str,
    normalized_author: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return a bounded deterministic set for cross-media identity reuse."""

    return _records(
        db,
        select(LibraryWork.__table__)
        .where(
            LibraryWork.normalized_title == normalized_title,
            LibraryWork.normalized_author == normalized_author,
        )
        .order_by(LibraryWork.created_at.asc(), LibraryWork.id.asc())
        .limit(limit),
    )


def get_media_version_by_id(
    db: Session, media_version_id: str
) -> dict[str, Any] | None:
    return _get_media_version(db, LibraryMediaVersion.id == media_version_id)


def get_media_version_format(
    db: Session, media_version_id: str
) -> dict[str, Any] | None:
    volume = db.scalar(
        select(LibraryVolume)
        .where(LibraryVolume.media_version_id == media_version_id)
        .order_by(LibraryVolume.sort_order, LibraryVolume.id)
        .limit(1)
    )
    if volume is None:
        return None
    return {"format": volume.format}


def get_media_version_cover_path(
    db: Session, media_version_id: str
) -> dict[str, Any] | None:
    volume = db.scalar(
        select(LibraryVolume)
        .where(
            LibraryVolume.media_version_id == media_version_id,
            LibraryVolume.cover_path.is_not(None),
        )
        .order_by(LibraryVolume.sort_order, LibraryVolume.id)
        .limit(1)
    )
    if volume is None:
        return None
    return {"coverPath": volume.cover_path}


def get_organize_job_for_work_media_version(
    db: Session, work_id: str, media_version_id: str
) -> dict[str, Any] | None:
    return _get_organize_job(
        db,
        OrganizeJob.work_id == work_id,
        OrganizeJob.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
    )


def get_metadata_lookup_task_id_by_import(
    db: Session, import_task_id: str
) -> dict[str, Any] | None:
    task = db.scalar(
        select(MetadataLookupTask.id).where(
            MetadataLookupTask.import_task_id == import_task_id
        )
    )
    return {"id": task} if task else None


def get_import_asset_by_task_and_path(
    db: Session,
    task_id: str,
    source_path: str,
) -> dict[str, Any] | None:
    return _get_import_asset(
        db,
        ImportAsset.import_task_id == task_id,
        ImportAsset.source_path == source_path,
    )


def get_pending_import_task_for_source(
    db: Session, source_path: str
) -> dict[str, Any] | None:
    return _get_import_task(
        db,
        ImportTask.source_path == source_path,
        ImportTask.status == "PENDING",
        order_by=(cast(ImportTask.created_at, Integer).asc(), ImportTask.id.asc()),
    )


def get_completed_import_task_for_source(
    db: Session, source_path: str
) -> dict[str, Any] | None:
    return _get_import_task(
        db,
        ImportTask.source_path == source_path,
        ImportTask.status == "COMPLETED",
    )


def fail_import_assets_for_task(
    db: Session,
    *,
    task_id: str,
    error_code: str,
    error_summary: str,
    updated_at: Any,
) -> None:
    db.execute(
        update(ImportAsset)
        .where(
            ImportAsset.import_task_id == task_id,
            ImportAsset.status != "COMPLETED",
        )
        .values(
            status="FAILED",
            error_code=error_code,
            error_summary=error_summary,
            updated_at=updated_at,
        )
    )


def sum_file_size_bytes_for_media_version(db: Session, media_version_id: str) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryFile.size_bytes), 0)).where(
                LibraryFile.volume_id.in_(
                    select(LibraryVolume.id).where(
                        LibraryVolume.media_version_id == media_version_id
                    )
                )
            ),
            0,
        )
    )


def sum_volume_chapter_count_for_media_version(
    db: Session, media_version_id: str
) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryVolume.chapter_count), 0)).where(
                LibraryVolume.media_version_id == media_version_id
            ),
            0,
        )
    )


def sum_volume_page_count_for_media_version(db: Session, media_version_id: str) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryVolume.page_count), 0)).where(
                LibraryVolume.media_version_id == media_version_id
            ),
            0,
        )
    )


def count_volumes_for_media_version(db: Session, media_version_id: str) -> int:
    return _count_volumes(db, LibraryVolume.media_version_id == media_version_id)


def list_volume_ordering_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _records(
        db,
        select(
            LibraryVolume.id.label("id"),
            LibraryVolume.title.label("title"),
            LibraryVolume.volume_index.label("volumeIndex"),
            LibraryVolume.sort_order.label("sortOrder"),
        )
        .where(LibraryVolume.media_version_id == media_version_id)
        .order_by(LibraryVolume.id.asc()),
    )


def count_media_versions_for_work(
    db: Session,
    work_id: str,
    *,
    media_kind: str | None = None,
) -> int:
    filters: list[Any] = [LibraryMediaVersion.work_id == work_id]
    if media_kind:
        filters.append(LibraryMediaVersion.media_kind == media_kind)
    return _count_media_versions(db, *filters)


def count_visible_media_versions_for_work(db: Session, work_id: str) -> int:
    return _count_media_versions(
        db,
        LibraryMediaVersion.work_id == work_id,
    )


def count_visible_volumes_for_work(db: Session, work_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(LibraryVolume)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(
                LibraryMediaVersion.work_id == work_id,
                LibraryVolume.hidden.is_(False),
            )
        )
        or 0
    )


def count_primary_audiobook_media_versions_for_work(
    db: Session,
    work_id: str,
    *,
    exclude_media_version_id: str,
) -> int:
    return _count_media_versions(
        db,
        LibraryMediaVersion.work_id == work_id,
        LibraryMediaVersion.media_kind == "AUDIOBOOK",
        LibraryMediaVersion.id != exclude_media_version_id,
    )


def count_audiobook_media_kind_media_versions(
    db: Session, work_id: str, media_kind: str
) -> int:
    return _count_media_versions(
        db,
        LibraryMediaVersion.work_id == work_id,
        LibraryMediaVersion.media_kind == media_kind,
    )


def sum_audio_file_size_for_media_version(db: Session, media_version_id: str) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryFile.size_bytes), 0)).where(
                LibraryFile.volume_id.in_(
                    select(LibraryVolume.id).where(
                        LibraryVolume.media_version_id == media_version_id
                    )
                ),
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def sum_audio_duration_for_media_version(db: Session, media_version_id: str) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryFile.duration_ms), 0)).where(
                LibraryFile.volume_id.in_(
                    select(LibraryVolume.id).where(
                        LibraryVolume.media_version_id == media_version_id
                    )
                ),
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def count_audio_files_for_media_version(db: Session, media_version_id: str) -> int:
    return _count_files(
        db,
        LibraryFile.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
        func.upper(LibraryFile.kind) == "AUDIO",
    )


def count_audio_chapters_for_media_version(db: Session, media_version_id: str) -> int:
    return _count_reading_units(
        db,
        LibraryReadingUnit.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
        LibraryReadingUnit.unit_type == "audio_chapter",
    )


def count_audio_chapters_for_volume(db: Session, volume_id: str) -> int:
    return _count_reading_units(
        db,
        LibraryReadingUnit.volume_id == volume_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
    )


def sum_audio_duration_for_volume(db: Session, volume_id: str) -> int:
    return int(
        _scalar_value(
            db,
            select(func.coalesce(func.sum(LibraryFile.duration_ms), 0)).where(
                LibraryFile.volume_id == volume_id,
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def list_library_files_by_paths(db: Session, paths: list[str]) -> list[dict[str, Any]]:
    if not paths:
        return []
    expanded: list[str] = []
    for path in paths:
        expanded.append(path)
        try:
            expanded.append(str(Path(path).resolve()))
        except OSError:
            pass
    unique_paths = list(dict.fromkeys(expanded))
    found: list[dict[str, Any]] = []
    for offset in range(0, len(unique_paths), 400):
        chunk = unique_paths[offset : offset + 400]
        rows = _list_library_files(db, LibraryFile.path.in_(chunk))
        found.extend(rows)
    deduped: dict[str, dict[str, Any]] = {}
    for row in found:
        deduped[str(row["id"])] = row
    return list(deduped.values())


def list_audio_files_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _list_library_files(
        db,
        LibraryFile.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
        func.upper(LibraryFile.kind) == "AUDIO",
        order_by=(LibraryFile.sort_order.asc(), LibraryFile.id.asc()),
    )


def list_audio_files_for_volume(
    db: Session, media_version_id: str, volume_id: str
) -> list[dict[str, Any]]:
    return _list_library_files(
        db,
        LibraryFile.volume_id == volume_id,
        func.upper(LibraryFile.kind) == "AUDIO",
        order_by=(LibraryFile.sort_order.asc(), LibraryFile.id.asc()),
    )


def list_audio_chapters_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _list_reading_units(
        db,
        LibraryReadingUnit.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(LibraryReadingUnit.sort_order.asc(), LibraryReadingUnit.id.asc()),
    )


def list_audio_chapters_for_file(db: Session, file_id: str) -> list[dict[str, Any]]:
    return _list_reading_units(
        db,
        LibraryReadingUnit.file_id == file_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.created_at.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def list_audio_chapter_units_for_file_ordered(
    db: Session, file_id: str
) -> list[dict[str, Any]]:
    return _list_reading_units(
        db,
        LibraryReadingUnit.file_id == file_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(
            func.coalesce(LibraryReadingUnit.start_ms, 0).asc(),
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.created_at.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def list_unassigned_audio_chapters_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    del db, media_version_id
    return []


def list_reading_progress_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _list_reading_progress(
        db,
        LibraryReadingProgress.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        ),
    )


def list_reading_progress_for_media_versions(
    db: Session,
    media_version_ids: list[str],
) -> list[dict[str, Any]]:
    if not media_version_ids:
        return []
    return _list_reading_progress(
        db,
        LibraryReadingProgress.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id.in_(media_version_ids)
            )
        ),
        order_by=(
            LibraryReadingProgress.updated_at.asc(),
            LibraryReadingProgress.created_at.asc(),
            LibraryReadingProgress.id.asc(),
        ),
    )


def list_audiobook_consumption_for_works(
    db: Session,
    work_ids: list[str],
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    return _records(
        db,
        select(UserMediaHistory.__table__)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == UserMediaHistory.media_version_id,
        )
        .where(
            LibraryMediaVersion.work_id.in_(work_ids),
            LibraryMediaVersion.media_kind == "AUDIOBOOK",
        )
        .order_by(UserMediaHistory.updated_at.asc(), UserMediaHistory.id.asc()),
    )


def list_media_versions_by_ids(
    db: Session, media_version_ids: list[str]
) -> list[dict[str, Any]]:
    if not media_version_ids:
        return []
    return _list_media_versions(db, LibraryMediaVersion.id.in_(media_version_ids))


def list_visible_media_versions_for_work_and_format(
    db: Session,
    work_id: str,
    fmt: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryMediaVersion.id, LibraryVolume.resource_key)
        .join(
            LibraryVolume,
            LibraryVolume.media_version_id == LibraryMediaVersion.id,
        )
        .where(
            LibraryMediaVersion.work_id == work_id,
            func.upper(LibraryVolume.format) == fmt.upper(),
            func.coalesce(LibraryVolume.hidden, 0) == 0,
        )
        .order_by(LibraryVolume.created_at.asc(), LibraryVolume.id.asc())
    ).all()
    return [
        {"id": row.id, "resourceKey": row.resource_key, "format": fmt} for row in rows
    ]


def get_first_volume_for_media_version(
    db: Session, media_version_id: str
) -> dict[str, Any] | None:
    return _get_volume(
        db,
        LibraryVolume.media_version_id == media_version_id,
        order_by=(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        ),
    )


def get_volume_context_by_id(db: Session, volume_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(
                LibraryVolume.__table__,
                LibraryMediaVersion.work_id.label("workId"),
                LibraryMediaVersion.media_kind.label("mediaKind"),
            )
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(LibraryVolume.id == volume_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def find_volume_conflict(
    db: Session,
    media_version_id: str,
    volume_index: float | None,
    volume_title: str,
) -> dict[str, Any] | None:
    if volume_index is None:
        return None
    row = (
        db.execute(
            select(LibraryVolume.__table__)
            .where(
                LibraryVolume.media_version_id == media_version_id,
                LibraryVolume.volume_index == volume_index,
                func.coalesce(LibraryVolume.hidden, False).is_(False),
            )
            .order_by(LibraryVolume.created_at.asc(), LibraryVolume.id.asc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def find_audio_media_version_by_resource_key(
    db: Session, resource_key: str
) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(LibraryMediaVersion.__table__)
            .join(
                LibraryVolume,
                LibraryVolume.media_version_id == LibraryMediaVersion.id,
            )
            .where(
                LibraryVolume.resource_key == resource_key,
                func.coalesce(LibraryVolume.hidden, 0) == 0,
            )
            .order_by(LibraryVolume.created_at.asc(), LibraryVolume.id.asc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def find_media_version_resource_key_conflict(
    db: Session,
    work_id: str,
    resource_key: str,
    exclude_media_version_id: str,
) -> dict[str, Any] | None:
    volume = (
        db.execute(
            select(LibraryVolume.__table__)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(
                LibraryMediaVersion.work_id == work_id,
                LibraryVolume.resource_key == resource_key,
                LibraryMediaVersion.id != exclude_media_version_id,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(volume) if volume else None


def list_volume_cover_paths_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, Any]]:
    return _list_volumes(
        db,
        LibraryVolume.media_version_id == media_version_id,
        LibraryVolume.cover_path.is_not(None),
        LibraryVolume.cover_path != "",
        order_by=(
            case((LibraryVolume.volume_index.is_(None), 1), else_=0).asc(),
            LibraryVolume.volume_index.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
        ),
    )


def find_work_cover_media_version(db: Session, work_id: str) -> dict[str, Any] | None:
    volume = db.scalars(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryMediaVersion.work_id == work_id,
            func.coalesce(LibraryVolume.hidden, 0) == 0,
            LibraryVolume.cover_path.is_not(None),
            LibraryVolume.cover_path != "",
        )
        .order_by(
            case(
                (LibraryMediaVersion.media_kind == "EBOOK", 0),
                (LibraryMediaVersion.media_kind == "COMIC", 1),
                else_=2,
            ),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
        )
        .limit(1)
    ).first()
    return {"coverPath": volume.cover_path} if volume is not None else None


def has_generated_cover_path(db: Session, work_id: str, cover_path: str) -> bool:
    volume_match = db.scalar(
        select(LibraryVolume.cover_path)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.cover_path == cover_path,
        )
        .limit(1)
    )
    return volume_match is not None


def get_latest_audio_tags_metadata(
    db: Session, media_version_id: str
) -> dict[str, Any] | None:
    row = db.scalars(
        select(LibraryMetadata)
        .where(
            LibraryMetadata.volume_id.in_(
                select(LibraryVolume.id).where(
                    LibraryVolume.media_version_id == media_version_id
                )
            ),
            LibraryMetadata.source == "audio_tags",
        )
        .order_by(LibraryMetadata.updated_at.desc(), LibraryMetadata.id.desc())
        .limit(1)
    ).first()
    return {"rawJson": row.raw_json} if row is not None else None


def delete_audio_metadata_sources(db: Session, media_version_id: str) -> None:
    db.execute(
        delete(LibraryMetadata).where(
            LibraryMetadata.volume_id.in_(
                select(LibraryVolume.id).where(
                    LibraryVolume.media_version_id == media_version_id
                )
            ),
            LibraryMetadata.source.in_(("audio_tags", "audiobook_manifest")),
        )
    )


def detach_audio_chapters_for_media_version(db: Session, media_version_id: str) -> None:
    db.execute(
        delete(LibraryReadingUnit).where(
            LibraryReadingUnit.volume_id.in_(
                select(LibraryVolume.id).where(
                    LibraryVolume.media_version_id == media_version_id
                )
            ),
            LibraryReadingUnit.unit_type == "audio_chapter",
        )
    )


def detach_audio_chapters_for_media_version_or_files(
    db: Session,
    media_version_id: str,
    file_ids: list[str],
) -> None:
    filters = [
        LibraryReadingUnit.volume_id.in_(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == media_version_id
            )
        )
    ]
    if file_ids:
        filters = [
            or_(
                *filters,
                LibraryReadingUnit.file_id.in_(file_ids),
            )
        ]
    db.execute(delete(LibraryReadingUnit).where(*filters))


def copy_shelf_links_to_work(
    db: Session, source_work_ids: list[str], target_work_id: str
) -> None:
    if not source_work_ids:
        return
    source_links = db.scalars(
        select(ShelfWork.shelf_id).where(ShelfWork.work_id.in_(source_work_ids))
    ).all()
    now = db_timestamp()
    for shelf_id in source_links:
        db.execute(
            sqlite_insert(ShelfWork)
            .values(shelf_id=shelf_id, work_id=target_work_id, created_at=now)
            .prefix_with("OR IGNORE")
        )


def find_deferred_source_volume(
    db: Session,
    *,
    source_path: str,
    work_id: str,
    result_volume_id: str | None,
) -> dict[str, Any] | None:
    row = db.execute(
        select(
            LibraryVolume.id,
            LibraryMediaVersion.media_kind,
        )
        .join(LibraryFile, LibraryFile.volume_id == LibraryVolume.id)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryFile.path == source_path,
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.id != result_volume_id,
            func.upper(LibraryVolume.format).in_(
                ("MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT")
            ),
            func.coalesce(LibraryVolume.hidden, 0) == 0,
        )
        .order_by(LibraryVolume.created_at.asc())
        .limit(1)
    ).first()
    return {"id": row.id, "mediaKind": row.media_kind} if row else None


def existing_file_import_snapshot(db: Session, path: Path) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(
                LibraryFile.volume_id.label("volumeId"),
                LibraryMediaVersion.id.label("mediaVersionId"),
                LibraryVolume.format,
                LibraryVolume.page_count,
                LibraryVolume.chapter_count,
                LibraryWork.id.label("workId"),
                LibraryWork.title,
            )
            .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .join(LibraryWork, LibraryWork.id == LibraryMediaVersion.work_id)
            .where(LibraryFile.path == str(path.resolve()))
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_file_volumes_by_paths(db: Session, paths: list[str]) -> list[dict[str, Any]]:
    if not paths:
        return []
    expanded: list[str] = []
    for path in paths:
        expanded.append(path)
        try:
            expanded.append(str(Path(path).resolve()))
        except OSError:
            pass
    rows = (
        db.execute(
            select(LibraryFile.path, LibraryFile.volume_id).where(
                LibraryFile.path.in_(list(dict.fromkeys(expanded)))
            )
        )
        .mappings()
        .all()
    )
    return [{"path": row["path"], "volumeId": row["volume_id"]} for row in rows]


def audio_bundle_fully_imported(db: Session, paths: list[str]) -> bool:
    if not paths:
        return False
    rows = db.execute(
        select(LibraryFile.volume_id)
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .where(
            LibraryFile.path.in_(paths),
            func.coalesce(LibraryVolume.hidden, 0) == 0,
        )
    ).all()
    volume_ids = {str(row[0] or "") for row in rows}
    return len(rows) == len(paths) and len(volume_ids) == 1


def get_monitor_folder_shelf_id(db: Session, monitor_folder_id: str) -> str | None:
    return db.scalar(
        select(MonitorFolder.shelf_id).where(MonitorFolder.id == monitor_folder_id)
    )


def shelf_exists(db: Session, shelf_id: str) -> bool:
    return (
        db.scalar(
            select(Shelf.id).where(
                Shelf.id == shelf_id,
                Shelf.kind == "STATIC",
            )
        )
        is not None
    )


def add_work_to_shelf(
    db: Session, shelf_id: str, work_id: str, *, created_at: Any
) -> None:
    if not shelf_exists(db, shelf_id):
        return
    db.execute(
        sqlite_insert(ShelfWork)
        .values(shelf_id=shelf_id, work_id=work_id, created_at=created_at)
        .prefix_with("OR IGNORE")
    )


def touch_shelf_updated_at(db: Session, shelf_id: str, *, updated_at: Any) -> None:
    db.execute(update(Shelf).where(Shelf.id == shelf_id).values(updated_at=updated_at))


def complete_download_task_for_source(
    db: Session,
    *,
    source_path: str,
    book_id: str,
    updated_at: Any,
) -> None:
    db.execute(
        update(DownloadTask)
        .where(DownloadTask.file_path == source_path)
        .values(
            book_id=book_id, status="completed", progress=100, updated_at=updated_at
        )
    )

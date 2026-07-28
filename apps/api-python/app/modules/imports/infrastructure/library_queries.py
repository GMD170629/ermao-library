"""ORM queries for import worker library and task side effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Integer, case, cast, delete, func, inspect as sa_inspect, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.import_pipeline import BookConversionTask, DownloadTask, ImportAsset, ImportTask
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.settings import MonitorFolder
from app.models.shelf import Shelf, ShelfWork
from app.models.common import db_timestamp
from app.modules.imports.infrastructure.legacy_persistence import (
    count_entities,
    get_entity,
    legacy_get_by_id,
    list_entities,
    scalar_select,
)
from app.modules.imports.infrastructure.schema import entity_as_legacy_dict, has_table, reflected_table, table_columns


def get_conversion_by_import_task_id(db: Session, import_task_id: str) -> dict[str, Any] | None:
    if not has_table(db, "BookConversionTask"):
        return None
    return get_entity(db, "BookConversionTask", BookConversionTask.import_task_id == import_task_id)


def get_import_task_by_id(db: Session, task_id: str) -> dict[str, Any] | None:
    return legacy_get_by_id(db, "ImportTask", task_id)


def get_work_by_id(db: Session, work_id: str) -> dict[str, Any] | None:
    return legacy_get_by_id(db, "LibraryWork", work_id)


def get_work_by_merge_key(db: Session, merge_key: str) -> dict[str, Any] | None:
    return get_entity(db, "LibraryWork", LibraryWork.merge_key == merge_key)


def get_edition_by_id(db: Session, edition_id: str) -> dict[str, Any] | None:
    return legacy_get_by_id(db, "LibraryEdition", edition_id)


def get_edition_format(db: Session, edition_id: str) -> dict[str, Any] | None:
    edition = db.get(LibraryEdition, edition_id)
    if edition is None:
        return None
    return {"format": edition.format}


def get_edition_cover_path(db: Session, edition_id: str) -> dict[str, Any] | None:
    edition = db.get(LibraryEdition, edition_id)
    if edition is None:
        return None
    return {"coverPath": edition.cover_path}


def get_organize_job_for_work_edition(db: Session, work_id: str, edition_id: str) -> dict[str, Any] | None:
    return get_entity(
        db,
        "OrganizeJob",
        OrganizeJob.work_id == work_id,
        OrganizeJob.edition_id == edition_id,
    )


def get_metadata_lookup_task_id_by_import(db: Session, import_task_id: str) -> dict[str, Any] | None:
    if not has_table(db, "MetadataLookupTask"):
        return None
    task = db.scalar(
        select(MetadataLookupTask.id).where(MetadataLookupTask.import_task_id == import_task_id)
    )
    return {"id": task} if task else None


def get_import_asset_by_task_and_path(
    db: Session,
    task_id: str,
    source_path: str,
) -> dict[str, Any] | None:
    if not has_table(db, "ImportAsset"):
        return None
    return get_entity(
        db,
        "ImportAsset",
        ImportAsset.import_task_id == task_id,
        ImportAsset.source_path == source_path,
    )


def get_pending_import_task_for_source(db: Session, source_path: str) -> dict[str, Any] | None:
    return get_entity(
        db,
        "ImportTask",
        ImportTask.source_path == source_path,
        ImportTask.status == "PENDING",
        order_by=(cast(ImportTask.created_at, Integer).asc(), ImportTask.id.asc()),
    )


def get_completed_import_task_for_source(db: Session, source_path: str) -> dict[str, Any] | None:
    return get_entity(
        db,
        "ImportTask",
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
    if not has_table(db, "ImportAsset"):
        return
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


def sum_file_size_bytes_for_edition(db: Session, edition_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryFile.size_bytes), 0)).where(
                LibraryFile.edition_id == edition_id
            ),
            0,
        )
    )


def sum_volume_chapter_count_for_edition(db: Session, edition_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryVolume.chapter_count), 0)).where(
                LibraryVolume.edition_id == edition_id
            ),
            0,
        )
    )


def sum_volume_page_count_for_edition(db: Session, edition_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryVolume.page_count), 0)).where(
                LibraryVolume.edition_id == edition_id
            ),
            0,
        )
    )


def count_volumes_for_edition(db: Session, edition_id: str) -> int:
    return count_entities(db, "LibraryVolume", LibraryVolume.edition_id == edition_id)


def count_editions_for_work(
    db: Session,
    work_id: str,
    *,
    media_kind: str | None = None,
) -> int:
    filters: list[Any] = [LibraryEdition.work_id == work_id]
    if media_kind and has_table(db, "LibraryEdition"):
        columns = {column["name"] for column in sa_inspect(db.connection()).get_columns("LibraryEdition")}
        if "mediaKind" in columns:
            filters.append(LibraryEdition.media_kind == media_kind)
    return count_entities(db, "LibraryEdition", *filters)


def count_visible_editions_for_work(db: Session, work_id: str) -> int:
    return count_entities(
        db,
        "LibraryEdition",
        LibraryEdition.work_id == work_id,
        func.coalesce(LibraryEdition.hidden, False).is_(False),
    )


def count_primary_audiobook_editions_for_work(
    db: Session,
    work_id: str,
    *,
    exclude_edition_id: str,
) -> int:
    return count_entities(
        db,
        "LibraryEdition",
        LibraryEdition.work_id == work_id,
        LibraryEdition.media_kind == "AUDIOBOOK",
        LibraryEdition.id != exclude_edition_id,
        func.coalesce(LibraryEdition.hidden, 0) == 0,
        LibraryEdition.is_primary.is_(True),
    )


def count_audiobook_media_kind_editions(db: Session, work_id: str, media_kind: str) -> int:
    return count_entities(
        db,
        "LibraryEdition",
        LibraryEdition.work_id == work_id,
        LibraryEdition.media_kind == media_kind,
        func.coalesce(LibraryEdition.hidden, 0) == 0,
    )


def sum_audio_file_size_for_edition(db: Session, edition_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryFile.size_bytes), 0)).where(
                LibraryFile.edition_id == edition_id,
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def sum_audio_duration_for_edition(db: Session, edition_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryFile.duration_ms), 0)).where(
                LibraryFile.edition_id == edition_id,
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def count_audio_files_for_edition(db: Session, edition_id: str) -> int:
    return count_entities(
        db,
        "LibraryFile",
        LibraryFile.edition_id == edition_id,
        func.upper(LibraryFile.kind) == "AUDIO",
    )


def count_audio_chapters_for_edition(db: Session, edition_id: str) -> int:
    return count_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.edition_id == edition_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
    )


def count_audio_chapters_for_volume(db: Session, volume_id: str) -> int:
    return count_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.volume_id == volume_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
    )


def sum_audio_duration_for_volume(db: Session, volume_id: str) -> int:
    return int(
        scalar_select(
            db,
            select(func.coalesce(func.sum(LibraryFile.duration_ms), 0)).where(
                LibraryFile.volume_id == volume_id,
                func.upper(LibraryFile.kind) == "AUDIO",
            ),
            0,
        )
    )


def list_library_files_by_paths(db: Session, paths: list[str]) -> list[dict[str, Any]]:
    if not paths or not has_table(db, "LibraryFile"):
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
        rows = list_entities(db, "LibraryFile", LibraryFile.path.in_(chunk))
        found.extend(rows)
    deduped: dict[str, dict[str, Any]] = {}
    for row in found:
        deduped[str(row["id"])] = row
    return list(deduped.values())


def list_audio_files_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryFile",
        LibraryFile.edition_id == edition_id,
        func.upper(LibraryFile.kind) == "AUDIO",
        order_by=(LibraryFile.sort_order.asc(), LibraryFile.id.asc()),
    )


def list_audio_files_for_volume(db: Session, edition_id: str, volume_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryFile",
        LibraryFile.edition_id == edition_id,
        LibraryFile.volume_id == volume_id,
        func.upper(LibraryFile.kind) == "AUDIO",
        order_by=(LibraryFile.sort_order.asc(), LibraryFile.id.asc()),
    )


def list_audio_chapters_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.edition_id == edition_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(LibraryReadingUnit.sort_order.asc(), LibraryReadingUnit.id.asc()),
    )


def list_audio_chapters_for_file(db: Session, file_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.file_id == file_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.created_at.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def list_audio_chapter_units_for_file_ordered(db: Session, file_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.file_id == file_id,
        LibraryReadingUnit.unit_type == "audio_chapter",
        order_by=(
            func.coalesce(LibraryReadingUnit.start_ms, 0).asc(),
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.created_at.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def list_unassigned_audio_chapters_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryReadingUnit",
        LibraryReadingUnit.edition_id == edition_id,
        LibraryReadingUnit.volume_id.is_(None),
        order_by=(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.created_at.asc(),
            LibraryReadingUnit.id.asc(),
        ),
    )


def list_reading_progress_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    if not has_table(db, "LibraryReadingProgress"):
        return []
    return list_entities(
        db,
        "LibraryReadingProgress",
        LibraryReadingProgress.edition_id == edition_id,
    )


def list_reading_progress_for_editions(
    db: Session,
    edition_ids: list[str],
) -> list[dict[str, Any]]:
    if not edition_ids or not has_table(db, "LibraryReadingProgress"):
        return []
    return list_entities(
        db,
        "LibraryReadingProgress",
        LibraryReadingProgress.edition_id.in_(edition_ids),
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
    if not work_ids or not has_table(db, "LibraryConsumptionState"):
        return []
    return list_entities(
        db,
        "LibraryConsumptionState",
        LibraryConsumptionState.work_id.in_(work_ids),
        func.upper(LibraryConsumptionState.media_kind) == "AUDIOBOOK",
        order_by=(
            LibraryConsumptionState.updated_at.asc(),
            LibraryConsumptionState.created_at.asc(),
            LibraryConsumptionState.id.asc(),
        ),
    )


def list_editions_by_ids(db: Session, edition_ids: list[str]) -> list[dict[str, Any]]:
    if not edition_ids:
        return []
    return list_entities(db, "LibraryEdition", LibraryEdition.id.in_(edition_ids))


def list_visible_editions_for_work_and_format(
    db: Session,
    work_id: str,
    fmt: str,
) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryEdition",
        LibraryEdition.work_id == work_id,
        LibraryEdition.format == fmt,
        func.coalesce(LibraryEdition.hidden, 0) == 0,
        order_by=(LibraryEdition.created_at.asc(),),
    )


def get_first_volume_for_edition(db: Session, edition_id: str) -> dict[str, Any] | None:
    return get_entity(
        db,
        "LibraryVolume",
        LibraryVolume.edition_id == edition_id,
        order_by=(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        ),
    )


def find_volume_conflict(
    db: Session,
    edition_id: str,
    volume_index: float | None,
    volume_title: str,
) -> dict[str, Any] | None:
    if volume_index is not None:
        return get_entity(
            db,
            "LibraryVolume",
            LibraryVolume.edition_id == edition_id,
            LibraryVolume.volume_index == volume_index,
        )
    return get_entity(
        db,
        "LibraryVolume",
        LibraryVolume.edition_id == edition_id,
        LibraryVolume.title == volume_title,
    )


def find_audio_edition_by_version_key(db: Session, version_key: str) -> dict[str, Any] | None:
    return get_entity(
        db,
        "LibraryEdition",
        LibraryEdition.version_key == version_key,
        func.upper(LibraryEdition.media_kind) == "AUDIOBOOK",
        func.coalesce(LibraryEdition.hidden, 0) == 0,
        order_by=(LibraryEdition.created_at.asc(), LibraryEdition.id.asc()),
    )


def find_edition_version_key_conflict(
    db: Session,
    work_id: str,
    version_key: str,
    exclude_edition_id: str,
) -> dict[str, Any] | None:
    return get_entity(
        db,
        "LibraryEdition",
        LibraryEdition.work_id == work_id,
        LibraryEdition.version_key == version_key,
        LibraryEdition.id != exclude_edition_id,
    )


def list_volume_cover_paths_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryVolume",
        LibraryVolume.edition_id == edition_id,
        LibraryVolume.cover_path.is_not(None),
        LibraryVolume.cover_path != "",
        order_by=(
            case((LibraryVolume.volume_index.is_(None), 1), else_=0).asc(),
            LibraryVolume.volume_index.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
        ),
    )


def find_work_cover_edition(db: Session, work_id: str) -> dict[str, Any] | None:
    edition = db.scalars(
        select(LibraryEdition)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, 0) == 0,
            LibraryEdition.cover_path.is_not(None),
            LibraryEdition.cover_path != "",
        )
        .order_by(
            case((LibraryEdition.is_primary.is_(True), 0), else_=1).asc(),
            LibraryEdition.created_at.asc(),
        )
        .limit(1)
    ).first()
    return {"coverPath": edition.cover_path} if edition is not None else None


def has_generated_cover_path(db: Session, work_id: str, cover_path: str) -> bool:
    edition_match = db.scalar(
        select(LibraryEdition.cover_path)
        .where(LibraryEdition.work_id == work_id, LibraryEdition.cover_path == cover_path)
        .limit(1)
    )
    if edition_match:
        return True
    volume_match = db.scalar(
        select(LibraryVolume.cover_path)
        .join(LibraryEdition, LibraryEdition.id == LibraryVolume.edition_id)
        .where(LibraryEdition.work_id == work_id, LibraryVolume.cover_path == cover_path)
        .limit(1)
    )
    return volume_match is not None


def get_latest_audio_tags_metadata(db: Session, edition_id: str) -> dict[str, Any] | None:
    row = db.scalars(
        select(LibraryMetadata)
        .where(
            LibraryMetadata.edition_id == edition_id,
            LibraryMetadata.source == "audio_tags",
        )
        .order_by(LibraryMetadata.updated_at.desc(), LibraryMetadata.id.desc())
        .limit(1)
    ).first()
    return {"rawJson": row.raw_json} if row is not None else None


def delete_audio_metadata_sources(db: Session, edition_id: str) -> None:
    db.execute(
        delete(LibraryMetadata).where(
            LibraryMetadata.edition_id == edition_id,
            LibraryMetadata.source.in_(("audio_tags", "audiobook_manifest")),
        )
    )


def detach_audio_chapters_for_edition(db: Session, edition_id: str) -> None:
    db.execute(
        update(LibraryReadingUnit)
        .where(
            LibraryReadingUnit.edition_id == edition_id,
            LibraryReadingUnit.unit_type == "audio_chapter",
        )
        .values(volume_id=None)
    )


def detach_audio_chapters_for_edition_or_files(
    db: Session,
    edition_id: str,
    file_ids: list[str],
) -> None:
    filters = [LibraryReadingUnit.edition_id == edition_id]
    if file_ids:
        filters = [or_(LibraryReadingUnit.edition_id == edition_id, LibraryReadingUnit.file_id.in_(file_ids))]
    db.execute(update(LibraryReadingUnit).where(*filters).values(volume_id=None))


def copy_shelf_links_to_work(db: Session, source_work_ids: list[str], target_work_id: str) -> None:
    if not source_work_ids or not has_table(db, "ShelfWork"):
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


def find_deferred_source_edition(
    db: Session,
    *,
    source_path: str,
    work_id: str,
    result_edition_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryEdition.id)
        .join(LibraryFile, LibraryFile.edition_id == LibraryEdition.id)
        .where(
            LibraryFile.path == source_path,
            LibraryEdition.work_id == work_id,
            LibraryEdition.id != result_edition_id,
            func.upper(LibraryEdition.format).in_(("MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT")),
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
        .order_by(LibraryEdition.created_at.asc())
        .limit(1)
    ).first()
    return {"id": row[0]} if row else None


def list_works_by_source_group_suffix(db: Session, source_group_suffix: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryWork.id, LibraryWork.title, LibraryWork.author)
        .join(LibraryEdition, LibraryEdition.work_id == LibraryWork.id)
        .where(
            LibraryEdition.source_group_key.like(f"%{source_group_suffix}"),
            func.coalesce(LibraryEdition.hidden, 0) == 0,
            func.coalesce(LibraryWork.hidden, 0) == 0,
        )
        .distinct()
        .order_by(LibraryWork.created_at.asc(), LibraryWork.id.asc())
    ).all()
    return [{"id": row.id, "title": row.title, "author": row.author} for row in rows]


def list_edition_file_paths_for_work(
    db: Session,
    work_id: str,
    source_group_suffix: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryFile.path)
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .where(
            LibraryEdition.work_id == work_id,
            LibraryEdition.source_group_key.like(f"%{source_group_suffix}"),
        )
        .order_by(LibraryFile.created_at.asc())
    ).all()
    return [{"path": row.path} for row in rows]


def existing_file_import_snapshot(db: Session, path: Path) -> dict[str, Any] | None:
    if not all(has_table(db, table) for table in ("LibraryFile", "LibraryEdition", "LibraryWork")):
        return None
    row = db.execute(
        select(
            LibraryFile.volume_id,
            LibraryEdition.id.label("editionId"),
            LibraryEdition.format,
            LibraryEdition.page_count,
            LibraryEdition.chapter_count,
            LibraryWork.id.label("workId"),
            LibraryWork.title,
            LibraryWork.work_type,
        )
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .join(LibraryWork, LibraryWork.id == LibraryEdition.work_id)
        .where(LibraryFile.path == str(path.resolve()))
        .limit(1)
    ).mappings().first()
    return dict(row) if row else None


def list_file_editions_by_paths(db: Session, paths: list[str]) -> list[dict[str, Any]]:
    if not paths:
        return []
    expanded: list[str] = []
    for path in paths:
        expanded.append(path)
        try:
            expanded.append(str(Path(path).resolve()))
        except OSError:
            pass
    rows = db.execute(
        select(LibraryFile.path, LibraryFile.edition_id).where(
            LibraryFile.path.in_(list(dict.fromkeys(expanded)))
        )
    ).mappings().all()
    return [{"path": row["path"], "editionId": row["edition_id"]} for row in rows]


def list_audio_files_by_fingerprint(
    db: Session,
    *,
    size_bytes: int,
    fingerprint: str,
) -> list[dict[str, Any]]:
    return list_entities(
        db,
        "LibraryFile",
        LibraryFile.size_bytes == size_bytes,
        LibraryFile.fingerprint == fingerprint,
        func.upper(LibraryFile.kind) == "AUDIO",
        order_by=(LibraryFile.created_at.asc(), LibraryFile.id.asc()),
    )


def audio_bundle_fully_imported(db: Session, paths: list[str]) -> bool:
    if not paths:
        return False
    rows = db.execute(
        select(LibraryFile.edition_id)
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .where(
            LibraryFile.path.in_(paths),
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
    ).all()
    edition_ids = {str(row[0] or "") for row in rows}
    return len(rows) == len(paths) and len(edition_ids) == 1


def get_monitor_folder_shelf_id(db: Session, monitor_folder_id: str) -> str | None:
    if not has_table(db, "MonitorFolder"):
        return None
    return db.scalar(
        select(MonitorFolder.shelf_id).where(MonitorFolder.id == monitor_folder_id)
    )


def shelf_exists(db: Session, shelf_id: str) -> bool:
    if not has_table(db, "Shelf"):
        return False
    return db.scalar(select(Shelf.id).where(Shelf.id == shelf_id)) is not None


def add_work_to_shelf(db: Session, shelf_id: str, work_id: str, *, created_at: Any) -> None:
    db.execute(
        sqlite_insert(ShelfWork)
        .values(shelf_id=shelf_id, work_id=work_id, created_at=created_at)
        .prefix_with("OR IGNORE")
    )


def touch_shelf_updated_at(db: Session, shelf_id: str, *, updated_at: Any) -> None:
    if not has_table(db, "Shelf"):
        return
    if "updatedAt" not in table_columns(db, "Shelf"):
        return
    table = reflected_table(db, "Shelf")
    db.execute(update(table).where(table.c.id == shelf_id).values({"updatedAt": updated_at}))


def complete_download_task_for_source(
    db: Session,
    *,
    source_path: str,
    book_id: str,
    updated_at: Any,
) -> None:
    if not has_table(db, "DownloadTask"):
        return
    db.execute(
        update(DownloadTask)
        .where(DownloadTask.file_path == source_path)
        .values(book_id=book_id, status="completed", progress=100, updated_at=updated_at)
    )

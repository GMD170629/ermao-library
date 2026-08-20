"""Focused ORM projections for scanner-owned imports and queue bookkeeping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import DownloadTask, ImportAsset, ImportTask
from app.models.library import LibraryFile, LibraryVersion, LibraryVolume, LibraryWork
from app.modules.library.infrastructure.media_kind_sql import (
    volume_effective_media_kind,
)


def _first_record(db: Session, statement: Any) -> dict[str, Any] | None:
    row = db.execute(statement.limit(1)).mappings().first()
    return dict(row) if row is not None else None


def _import_task(
    db: Session,
    *filters: Any,
    order_by: tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    statement = select(ImportTask.__table__).where(*filters)
    if order_by:
        statement = statement.order_by(*order_by)
    return _first_record(db, statement)


def get_import_task_by_id(db: Session, task_id: str) -> dict[str, Any] | None:
    return _import_task(db, ImportTask.id == task_id)


def get_completed_import_task_for_source(
    db: Session, source_path: str
) -> dict[str, Any] | None:
    return _import_task(
        db,
        ImportTask.source_path == source_path,
        ImportTask.status == "COMPLETED",
    )


def get_work_by_id(db: Session, work_id: str) -> dict[str, Any] | None:
    return _first_record(
        db,
        select(LibraryWork.__table__).where(LibraryWork.id == work_id),
    )


def get_import_asset_by_task_and_path(
    db: Session,
    task_id: str,
    source_path: str,
) -> dict[str, Any] | None:
    return _first_record(
        db,
        select(ImportAsset.__table__).where(
            ImportAsset.import_task_id == task_id,
            ImportAsset.source_path == source_path,
        ),
    )


def fail_import_assets_for_task(
    db: Session,
    *,
    task_id: str,
    error_code: str,
    error_summary: str,
    updated_at: object,
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


def get_volume_context_by_id(db: Session, volume_id: str) -> dict[str, Any] | None:
    return _first_record(
        db,
        select(
            LibraryVolume.__table__,
            LibraryVersion.work_id.label("workId"),
            volume_effective_media_kind(LibraryVolume).label("mediaKind"),
        )
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(LibraryVolume.id == volume_id),
    )


def list_volume_cover_paths_for_version(
    db: Session, version_id: str
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(LibraryVolume.__table__)
            .where(
                LibraryVolume.version_id == version_id,
                LibraryVolume.cover_path.is_not(None),
                LibraryVolume.cover_path != "",
            )
            .order_by(
                case((LibraryVolume.volume_index.is_(None), 1), else_=0),
                LibraryVolume.volume_index,
                LibraryVolume.sort_order,
                LibraryVolume.created_at,
                LibraryVolume.id,
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def find_work_cover_volume(db: Session, work_id: str) -> dict[str, Any] | None:
    volume = db.scalars(
        select(LibraryVolume)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(
            LibraryVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
            LibraryVolume.cover_path.is_not(None),
            LibraryVolume.cover_path != "",
        )
        .order_by(
            case(
                (volume_effective_media_kind(LibraryVolume) == "EBOOK", 0),
                (volume_effective_media_kind(LibraryVolume) == "COMIC", 1),
                else_=2,
            ),
            LibraryVolume.sort_order,
            LibraryVolume.created_at,
            LibraryVolume.id,
        )
        .limit(1)
    ).first()
    return {"coverPath": volume.cover_path} if volume is not None else None


def has_generated_cover_path(db: Session, work_id: str, cover_path: str) -> bool:
    return (
        db.scalar(
            select(LibraryVolume.id)
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
            .where(
                LibraryVersion.work_id == work_id,
                LibraryVolume.cover_path == cover_path,
            )
            .limit(1)
        )
        is not None
    )


def existing_file_import_snapshot(db: Session, path: Path) -> dict[str, Any] | None:
    return _first_record(
        db,
        select(
            LibraryFile.volume_id.label("volumeId"),
            LibraryVersion.id.label("versionId"),
            LibraryVolume.format,
            LibraryVolume.page_count,
            LibraryVolume.chapter_count,
            LibraryWork.id.label("workId"),
            LibraryWork.title,
        )
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .join(LibraryWork, LibraryWork.id == LibraryVersion.work_id)
        .where(
            LibraryFile.path == str(path.resolve()),
            LibraryVolume.import_status.in_(("COMPLETED", "IMPORTED", "READY")),
        ),
    )


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
    rows = db.execute(
        select(LibraryFile.path, LibraryFile.volume_id).where(
            LibraryFile.path.in_(tuple(dict.fromkeys(expanded))),
            LibraryFile.volume_id.in_(
                select(LibraryVolume.id).where(
                    LibraryVolume.import_status.in_(
                        ("COMPLETED", "IMPORTED", "READY")
                    )
                )
            ),
        )
    ).all()
    return [{"path": row.path, "volumeId": row.volume_id} for row in rows]


def audio_bundle_fully_imported(db: Session, paths: list[str]) -> bool:
    if not paths:
        return False
    rows = db.execute(
        select(LibraryFile.volume_id)
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .where(
            LibraryFile.path.in_(paths),
            LibraryVolume.hidden.is_(False),
        )
    ).all()
    volume_ids = {str(row.volume_id or "") for row in rows}
    return len(rows) == len(paths) and len(volume_ids) == 1


def complete_download_task_for_source(
    db: Session,
    *,
    source_path: str,
    book_id: str,
    updated_at: object,
) -> None:
    db.execute(
        update(DownloadTask)
        .where(DownloadTask.file_path == source_path)
        .values(
            book_id=book_id,
            status="completed",
            progress=100,
            updated_at=updated_at,
        )
    )

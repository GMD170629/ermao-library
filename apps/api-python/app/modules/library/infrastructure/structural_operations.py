"""ORM adapter for edition and volume structure changes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask, KindleSendTask
from app.models.library import (
    LibraryEdition,
    LibraryFile,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.application.dto import MoveVolumeResult


def _media_kind(format_name: str, stored_media_kind: str | None) -> str:
    if stored_media_kind:
        return stored_media_kind.upper()
    normalized = format_name.upper()
    if normalized == "COMIC":
        return "COMIC"
    if normalized in {"AUDIO", "AUDIOBOOK"}:
        return "AUDIOBOOK"
    return "EBOOK"


def _remaining_edition_id(db: Session, work_id: str) -> str | None:
    return db.scalar(
        select(LibraryEdition.id)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
        .order_by(
            func.coalesce(LibraryEdition.is_primary, 0).desc(),
            LibraryEdition.created_at.asc(),
            LibraryEdition.id.asc(),
        )
        .limit(1)
    )


def _refresh_work_primary(db: Session, work_id: str, now: datetime) -> None:
    remaining_id = _remaining_edition_id(db, work_id)
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            primary_edition_id=remaining_id,
            hidden=remaining_id is None,
            updated_at=now,
        )
    )


def _edition_totals(db: Session, edition_id: str) -> tuple[int, int, int]:
    row = db.execute(
        select(
            func.count(LibraryVolume.id),
            func.coalesce(func.sum(LibraryVolume.page_count), 0),
            func.coalesce(func.sum(LibraryVolume.chapter_count), 0),
        ).where(LibraryVolume.edition_id == edition_id)
    ).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _refresh_edition_totals(db: Session, edition_id: str, now: datetime) -> None:
    _count, pages, chapters = _edition_totals(db, edition_id)
    db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == edition_id)
        .values(page_count=pages, chapter_count=chapters, updated_at=now)
    )


def _reorder_edition_volumes(db: Session, edition_id: str, now: datetime) -> None:
    volume_ids = db.scalars(
        select(LibraryVolume.id)
        .where(LibraryVolume.edition_id == edition_id)
        .order_by(
            case((LibraryVolume.volume_index.is_(None), 1), else_=0).asc(),
            LibraryVolume.volume_index.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    for index, volume_id in enumerate(volume_ids):
        db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == volume_id)
            .values(sort_order=(index + 1) * 1000, updated_at=now)
        )


def _move_volume_references(
    db: Session,
    *,
    volume_id: str,
    target_work_id: str,
    target_edition_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(edition_id=target_edition_id, updated_at=now)
    )
    db.execute(
        update(LibraryFile)
        .where(LibraryFile.volume_id == volume_id)
        .values(edition_id=target_edition_id, updated_at=now)
    )
    db.execute(
        update(LibraryReadingUnit)
        .where(LibraryReadingUnit.volume_id == volume_id)
        .values(edition_id=target_edition_id, updated_at=now)
    )
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.volume_id == volume_id)
        .values(
            work_id=target_work_id,
            edition_id=target_edition_id,
            updated_at=now,
        )
    )
    db.execute(
        update(ImportTask)
        .where(ImportTask.volume_id == volume_id)
        .values(
            work_id=target_work_id,
            edition_id=target_edition_id,
            updated_at=now,
        )
    )
    if inspect(db.connection()).has_table("KindleSendTask"):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.volume_id == volume_id)
            .values(
                work_id=target_work_id,
                edition_id=target_edition_id,
                updated_at=now,
            )
        )


def _move_edition_references(
    db: Session,
    *,
    edition_id: str,
    target_work_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.edition_id == edition_id)
        .values(work_id=target_work_id, updated_at=now)
    )
    db.execute(
        update(ImportTask)
        .where(ImportTask.edition_id == edition_id)
        .values(work_id=target_work_id, updated_at=now)
    )
    if inspect(db.connection()).has_table("KindleSendTask"):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.edition_id == edition_id)
            .values(work_id=target_work_id, updated_at=now)
        )


def move_volume_to_work(
    db: Session,
    *,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    source_format: str,
    now: datetime,
) -> MoveVolumeResult:
    source_edition = db.execute(
        select(
            LibraryEdition.id,
            LibraryEdition.format,
            LibraryEdition.media_kind,
            LibraryEdition.version_key,
            LibraryEdition.is_primary,
        )
        .join(LibraryVolume, LibraryVolume.edition_id == LibraryEdition.id)
        .where(
            LibraryVolume.id == volume_id,
            LibraryEdition.work_id == source_work_id,
        )
    ).one_or_none()
    if source_edition is None:
        raise ValueError("卷册不存在或不属于该作品")

    source_edition_id = str(source_edition.id)
    source_media_kind = _media_kind(
        str(source_edition.format or source_format),
        source_edition.media_kind,
    )
    matching_primary = db.execute(
        select(LibraryEdition.id)
        .where(
            LibraryEdition.work_id == target_work_id,
            func.upper(LibraryEdition.format) == source_format.upper(),
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
        .order_by(
            func.coalesce(LibraryEdition.is_primary, 0).desc(),
            LibraryEdition.created_at.asc(),
            LibraryEdition.id.asc(),
        )
        .limit(1)
    ).one_or_none()
    source_volume_count, _pages, _chapters = _edition_totals(db, source_edition_id)
    matching_volume_count = (
        _edition_totals(db, str(matching_primary.id))[0]
        if matching_primary is not None
        else 0
    )
    merge_volumes = bool(
        matching_primary is not None
        and source_volume_count > 0
        and matching_volume_count > 0
    )

    if merge_volumes:
        target_edition_id = str(matching_primary.id)
        _move_volume_references(
            db,
            volume_id=volume_id,
            target_work_id=target_work_id,
            target_edition_id=target_edition_id,
            now=now,
        )
        remaining_count, _pages, _chapters = _edition_totals(db, source_edition_id)
        _refresh_edition_totals(db, source_edition_id, now)
        direct_file_count = int(
            db.scalar(
                select(func.count(LibraryFile.id)).where(
                    LibraryFile.edition_id == source_edition_id,
                    LibraryFile.volume_id.is_(None),
                )
            )
            or 0
        )
        if remaining_count == 0 and direct_file_count == 0:
            db.execute(
                update(LibraryEdition)
                .where(LibraryEdition.id == source_edition_id)
                .values(is_primary=False, hidden=True, updated_at=now)
            )
            if bool(source_edition.is_primary):
                replacement_id = db.scalar(
                    select(LibraryEdition.id)
                    .where(
                        LibraryEdition.work_id == source_work_id,
                        LibraryEdition.media_kind == source_media_kind,
                        func.coalesce(LibraryEdition.hidden, 0) == 0,
                    )
                    .order_by(
                        func.coalesce(LibraryEdition.is_primary, 0).desc(),
                        LibraryEdition.created_at.asc(),
                        LibraryEdition.id.asc(),
                    )
                    .limit(1)
                )
                if replacement_id is not None:
                    db.execute(
                        update(LibraryEdition)
                        .where(LibraryEdition.id == replacement_id)
                        .values(is_primary=True, updated_at=now)
                    )
            _refresh_work_primary(db, source_work_id, now)
        _reorder_edition_volumes(db, target_edition_id, now)
        _refresh_edition_totals(db, target_edition_id, now)
        transfer_mode = "MERGED_VOLUME"
    else:
        target_edition_id = source_edition_id
        existing_media_id = db.scalar(
            select(LibraryEdition.id)
            .where(
                LibraryEdition.work_id == target_work_id,
                LibraryEdition.media_kind == source_media_kind,
                func.coalesce(LibraryEdition.hidden, 0) == 0,
            )
            .limit(1)
        )
        transfer_mode = (
            "ADDED_MEDIA" if existing_media_id is None else "ADDED_BACKUP_EDITION"
        )
        desired_version_key = str(source_edition.version_key or source_edition_id)
        version_key = desired_version_key
        suffix = 1
        while db.scalar(
            select(LibraryEdition.id)
            .where(
                LibraryEdition.work_id == target_work_id,
                LibraryEdition.version_key == version_key,
                LibraryEdition.id != source_edition_id,
            )
            .limit(1)
        ):
            suffix += 1
            version_key = f"{desired_version_key}:backup-{suffix}"
        db.execute(
            update(LibraryEdition)
            .where(LibraryEdition.id == source_edition_id)
            .values(
                work_id=target_work_id,
                version_key=version_key,
                is_primary=existing_media_id is None,
                updated_at=now,
            )
        )
        _move_edition_references(
            db,
            edition_id=source_edition_id,
            target_work_id=target_work_id,
            now=now,
        )
        _refresh_work_primary(db, source_work_id, now)

    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id.in_([source_work_id, target_work_id]))
        .values(updated_at=now)
    )
    db.flush()
    return MoveVolumeResult(
        source_edition_id=source_edition_id,
        target_edition_id=target_edition_id,
        target_work_id=target_work_id,
        transfer_mode=transfer_mode,
        merged_volume=merge_volumes,
    )


def reorder_volume(
    db: Session,
    *,
    volume_id: str,
    edition_id: str,
    direction: str,
    now: datetime,
) -> bool:
    volumes = db.execute(
        select(LibraryVolume.id, LibraryVolume.sort_order)
        .where(LibraryVolume.edition_id == edition_id)
        .order_by(LibraryVolume.sort_order.asc(), LibraryVolume.id.asc())
    ).all()
    index = next(
        (item_index for item_index, item in enumerate(volumes) if item.id == volume_id),
        -1,
    )
    target_index = index - 1 if direction == "up" else index + 1
    if index < 0 or target_index < 0 or target_index >= len(volumes):
        return False
    target = volumes[target_index]
    current = volumes[index]
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == current.id)
        .values(sort_order=target.sort_order or 0, updated_at=now)
    )
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == target.id)
        .values(sort_order=current.sort_order or 0, updated_at=now)
    )
    db.flush()
    return True

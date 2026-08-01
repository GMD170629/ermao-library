"""ORM adapter for media-version and volume structure changes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.common import cuid
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.modules.library.application.dto import MoveVolumeResult


def _media_version_for_work(
    db: Session, *, work_id: str, media_kind: str
) -> LibraryMediaVersion | None:
    return db.scalar(
        select(LibraryMediaVersion)
        .where(
            LibraryMediaVersion.work_id == work_id,
            LibraryMediaVersion.media_kind == media_kind,
        )
        .limit(1)
    )


def _ensure_media_version(
    db: Session, *, work_id: str, media_kind: str, now: datetime
) -> tuple[LibraryMediaVersion, bool]:
    existing = _media_version_for_work(db, work_id=work_id, media_kind=media_kind)
    if existing is not None:
        return existing, False
    media_version = LibraryMediaVersion(
        id=cuid(),
        work_id=work_id,
        media_kind=media_kind,
        created_at=now,
        updated_at=now,
    )
    db.add(media_version)
    db.flush()
    return media_version, True


def _reorder_media_version_volumes(
    db: Session, media_version_id: str, now: datetime
) -> None:
    volume_ids = db.scalars(
        select(LibraryVolume.id)
        .where(LibraryVolume.media_version_id == media_version_id)
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    for index, volume_id in enumerate(volume_ids, start=1):
        db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == volume_id)
            .values(sort_order=index * 1000, updated_at=now)
        )


def _remove_empty_media_version(
    db: Session, *, media_version_id: str, work_id: str
) -> None:
    remaining = int(
        db.scalar(
            select(func.count(LibraryVolume.id)).where(
                LibraryVolume.media_version_id == media_version_id
            )
        )
        or 0
    )
    if remaining:
        return
    db.execute(
        delete(LibraryMediaVersion).where(LibraryMediaVersion.id == media_version_id)
    )
    remaining_media = int(
        db.scalar(
            select(func.count(LibraryMediaVersion.id)).where(
                LibraryMediaVersion.work_id == work_id
            )
        )
        or 0
    )
    if remaining_media == 0:
        db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))


def move_volume_to_work(
    db: Session,
    *,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    now: datetime,
) -> MoveVolumeResult:
    """Move one resource without using a volume number as identity."""

    source = db.execute(
        select(LibraryVolume, LibraryMediaVersion)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryMediaVersion.work_id == source_work_id,
        )
    ).one_or_none()
    if source is None:
        raise ValueError("卷册不存在或不属于该作品")
    if db.get(LibraryWork, target_work_id) is None:
        raise ValueError("目标作品不存在")

    volume, source_media_version = source
    target_media_version, created = _ensure_media_version(
        db,
        work_id=target_work_id,
        media_kind=source_media_version.media_kind,
        now=now,
    )
    source_media_version_id = source_media_version.id
    volume.media_version_id = target_media_version.id
    volume.updated_at = now
    db.flush()

    _reorder_media_version_volumes(db, source_media_version_id, now)
    _reorder_media_version_volumes(db, target_media_version.id, now)
    _remove_empty_media_version(
        db,
        media_version_id=source_media_version_id,
        work_id=source_work_id,
    )
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == target_work_id)
        .values(updated_at=now)
    )
    db.flush()
    return MoveVolumeResult(
        source_media_version_id=source_media_version_id,
        target_media_version_id=target_media_version.id,
        target_work_id=target_work_id,
        transfer_mode=("CREATED_MEDIA_VERSION" if created else "APPENDED_VOLUME"),
    )


def reorder_volume(
    db: Session,
    *,
    volume_id: str,
    media_version_id: str,
    direction: str,
    now: datetime,
) -> bool:
    volumes = db.execute(
        select(LibraryVolume.id, LibraryVolume.sort_order)
        .where(LibraryVolume.media_version_id == media_version_id)
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
        .values(sort_order=target.sort_order, updated_at=now)
    )
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == target.id)
        .values(sort_order=current.sort_order, updated_at=now)
    )
    db.flush()
    return True

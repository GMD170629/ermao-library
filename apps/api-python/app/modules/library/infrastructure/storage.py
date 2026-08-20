"""Volume-scoped library file, cover, and storage queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def get_file(db: Session, file_id: str) -> dict[str, object] | None:
    file = db.get(LibraryFile, file_id)
    return entity_as_legacy_dict(file) if file is not None else None


def first_file_for_volume(db: Session, *, volume_id: str) -> dict[str, object] | None:
    file = db.scalar(
        select(LibraryFile)
        .where(LibraryFile.volume_id == volume_id)
        .order_by(
            LibraryFile.sort_order.asc(),
            LibraryFile.created_at.asc(),
            LibraryFile.id.asc(),
        )
        .limit(1)
    )
    return entity_as_legacy_dict(file) if file is not None else None


def get_cover_record(
    db: Session,
    *,
    work_id: str | None = None,
    volume_id: str | None = None,
) -> dict[str, object] | None:
    record = (
        db.get(LibraryWork, work_id)
        if work_id is not None
        else db.get(LibraryVolume, volume_id)
        if volume_id is not None
        else None
    )
    return entity_as_legacy_dict(record) if record is not None else None


def update_cover_record(
    db: Session,
    *,
    record_type: str,
    record_id: str,
    cover_path: str,
    cover_status: str | None,
    now: datetime,
) -> None:
    model = LibraryWork if record_type == "LibraryWork" else LibraryVolume
    values: dict[str, object] = {"cover_path": cover_path, "updated_at": now}
    if cover_status is not None:
        values["cover_status"] = cover_status
    db.execute(update(model).where(model.id == record_id).values(**values))
    db.flush()


def preferred_work_cover_path(db: Session, work_id: str) -> str | None:
    cover = db.scalar(
        select(LibraryVolume.cover_path)
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(
            LibraryVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
            LibraryVolume.cover_path.is_not(None),
            LibraryVolume.cover_path != "",
        )
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(1)
    )
    return str(cover) if cover else None


def update_work_cover(
    db: Session,
    *,
    work_id: str,
    cover_path: str,
    cover_status: str,
    now: datetime,
) -> bool:
    result = db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            cover_path=cover_path,
            cover_status=cover_status,
            updated_at=now,
        )
    )
    return bool(result.rowcount)


def update_work_covers(
    db: Session,
    rows: tuple[dict[str, object], ...],
) -> int:
    if not rows:
        return 0
    db.execute(update(LibraryWork), list(rows))
    return len(rows)


def collect_storage_values(
    db: Session, work_id: str
) -> tuple[
    str | None,
    list[dict[str, object]],
    list[dict[str, object]],
]:
    work_cover = db.scalar(
        select(LibraryWork.cover_path).where(LibraryWork.id == work_id)
    )
    volumes = db.scalars(
        select(LibraryVolume)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(LibraryVersion.work_id == work_id)
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    volume_ids = [volume.id for volume in volumes]
    files = (
        db.scalars(
            select(LibraryFile).where(LibraryFile.volume_id.in_(volume_ids))
        ).all()
        if volume_ids
        else []
    )
    return (
        work_cover,
        [entity_as_legacy_dict(volume) for volume in volumes],
        [entity_as_legacy_dict(file) for file in files],
    )

"""Typed MediaVersion-to-Volume joins for library adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingUnit,
    LibraryVolume,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def get_volume_context(db: Session, volume_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryVolume, LibraryMediaVersion)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryVolume.id == volume_id)
    ).first()
    if row is None:
        return None
    volume, media_version = row
    payload = entity_as_legacy_dict(volume)
    payload.update(
        workId=media_version.work_id,
        mediaKind=media_version.media_kind,
        mediaVersionId=media_version.id,
    )
    return payload


def get_unit_context(db: Session, unit_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadingUnit, LibraryVolume, LibraryMediaVersion)
        .join(LibraryVolume, LibraryVolume.id == LibraryReadingUnit.volume_id)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryReadingUnit.id == unit_id)
    ).first()
    if row is None:
        return None
    unit, volume, media_version = row
    payload = entity_as_legacy_dict(unit)
    payload.update(
        workId=media_version.work_id,
        mediaKind=media_version.media_kind,
        mediaVersionId=media_version.id,
        format=volume.format,
    )
    return payload


def list_file_paths_for_work(db: Session, work_id: str) -> list[str]:
    paths = db.scalars(
        select(LibraryFile.path)
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryMediaVersion.work_id == work_id)
    ).all()
    return [str(path) for path in paths if path]


def get_volume_for_work(
    db: Session, *, volume_id: str, work_id: str
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryVolume, LibraryMediaVersion)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
        )
    ).first()
    if row is None:
        return None
    volume, media_version = row
    payload = entity_as_legacy_dict(volume)
    payload.update(
        sourceWorkId=media_version.work_id,
        sourceFormat=volume.format,
        mediaVersionId=media_version.id,
    )
    return payload


def get_volume_belonging_to_work(
    db: Session, *, volume_id: str, work_id: str
) -> dict[str, Any] | None:
    return get_volume_for_work(db, volume_id=volume_id, work_id=work_id)

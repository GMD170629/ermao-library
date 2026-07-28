"""Fixed-model ORM joins used by library compatibility adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryEdition,
    LibraryFile,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def get_volume_with_edition(db: Session, volume_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryVolume, LibraryEdition)
        .join(LibraryEdition, LibraryEdition.id == LibraryVolume.edition_id)
        .where(LibraryVolume.id == volume_id)
    ).first()
    if row is None:
        return None
    volume, edition = row
    payload = entity_as_legacy_dict(volume)
    payload.update(
        workId=edition.work_id,
        mediaKind=edition.media_kind,
        format=edition.format,
        editionHidden=edition.hidden,
    )
    return payload


def get_unit_with_edition(db: Session, unit_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadingUnit, LibraryEdition)
        .join(LibraryEdition, LibraryEdition.id == LibraryReadingUnit.edition_id)
        .where(LibraryReadingUnit.id == unit_id)
    ).first()
    if row is None:
        return None
    unit, edition = row
    payload = entity_as_legacy_dict(unit)
    payload.update(
        workId=edition.work_id,
        mediaKind=edition.media_kind,
        format=edition.format,
        editionHidden=edition.hidden,
    )
    return payload


def list_file_paths_for_work(db: Session, work_id: str) -> list[str]:
    return [
        str(path)
        for path in db.scalars(
            select(LibraryFile.path)
            .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
            .where(
                LibraryEdition.work_id == work_id,
                LibraryFile.path.is_not(None),
            )
        ).all()
        if path
    ]


def get_primary_edition_row(db: Session, work_id: str) -> dict[str, Any] | None:
    primary_rank = case(
        (LibraryEdition.id == LibraryWork.primary_edition_id, 0),
        (func.coalesce(LibraryEdition.is_primary, False).is_(True), 1),
        else_=2,
    )
    edition = db.scalar(
        select(LibraryEdition)
        .outerjoin(LibraryWork, LibraryWork.id == LibraryEdition.work_id)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, False).is_(False),
        )
        .order_by(primary_rank.asc(), LibraryEdition.created_at.asc())
        .limit(1)
    )
    return entity_as_legacy_dict(edition) if edition is not None else None


def get_volume_for_work(
    db: Session,
    *,
    volume_id: str,
    work_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryVolume, LibraryEdition)
        .join(LibraryEdition, LibraryEdition.id == LibraryVolume.edition_id)
        .where(
            LibraryVolume.id == volume_id,
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, False).is_(False),
        )
    ).first()
    if row is None:
        return None
    volume, edition = row
    payload = entity_as_legacy_dict(volume)
    payload.update(sourceWorkId=edition.work_id, sourceFormat=edition.format)
    return payload


def get_edition_with_work_title(
    db: Session,
    edition_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryEdition, LibraryWork.title)
        .join(LibraryWork, LibraryWork.id == LibraryEdition.work_id)
        .where(
            LibraryEdition.id == edition_id,
            func.coalesce(LibraryEdition.hidden, False).is_(False),
        )
    ).first()
    if row is None:
        return None
    edition, work_title = row
    payload = entity_as_legacy_dict(edition)
    payload["targetWorkTitle"] = work_title
    return payload


def get_volume_belonging_to_work(
    db: Session,
    *,
    volume_id: str,
    work_id: str,
) -> dict[str, Any] | None:
    volume = db.scalar(
        select(LibraryVolume)
        .join(LibraryEdition, LibraryEdition.id == LibraryVolume.edition_id)
        .where(
            LibraryVolume.id == volume_id,
            LibraryEdition.work_id == work_id,
        )
    )
    return entity_as_legacy_dict(volume) if volume is not None else None

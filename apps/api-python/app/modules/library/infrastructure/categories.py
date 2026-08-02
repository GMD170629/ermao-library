"""ORM persistence for library category merge and rename side effects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFacet,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def get_facet(db: Session, facet_id: str) -> dict[str, Any] | None:
    facet = db.get(LibraryFacet, facet_id)
    return entity_as_legacy_dict(facet) if facet is not None else None


def get_facet_of_kind(db: Session, facet_id: str, kind: str) -> dict[str, Any] | None:
    facet = db.execute(
        select(LibraryFacet).where(
            LibraryFacet.id == facet_id, LibraryFacet.kind == kind
        )
    ).scalar_one_or_none()
    return entity_as_legacy_dict(facet) if facet is not None else None


def find_normalized_name_conflict(
    db: Session,
    *,
    kind: str,
    normalized_name: str,
    exclude_facet_id: str,
) -> str | None:
    return db.execute(
        select(LibraryFacet.id).where(
            LibraryFacet.kind == kind,
            LibraryFacet.normalized_name == normalized_name,
            LibraryFacet.id != exclude_facet_id,
        )
    ).scalar_one_or_none()


def list_work_facet_links(db: Session, facet_ids: list[str]) -> list[dict[str, Any]]:
    if not facet_ids:
        return []
    rows = (
        db.execute(
            select(LibraryWorkFacet).where(LibraryWorkFacet.facet_id.in_(facet_ids))
        )
        .scalars()
        .all()
    )
    return [entity_as_legacy_dict(row) for row in rows]


def list_volume_facet_links(db: Session, facet_ids: list[str]) -> list[dict[str, Any]]:
    if not facet_ids:
        return []
    rows = (
        db.execute(
            select(LibraryVolumeFacet).where(LibraryVolumeFacet.facet_id.in_(facet_ids))
        )
        .scalars()
        .all()
    )
    return [entity_as_legacy_dict(row) for row in rows]


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.get(LibraryWork, work_id)
    return entity_as_legacy_dict(work) if work is not None else None


def get_volume(db: Session, volume_id: str) -> dict[str, Any] | None:
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
    result = entity_as_legacy_dict(volume)
    result["workId"] = media_version.work_id
    return result


def list_work_ids_for_facet(db: Session, facet_id: str) -> list[str]:
    return [
        str(work_id)
        for work_id in db.execute(
            select(LibraryWorkFacet.work_id).where(
                LibraryWorkFacet.facet_id == facet_id
            )
        ).scalars()
    ]


def list_volume_ids_for_facet(db: Session, facet_id: str) -> list[str]:
    return [
        str(volume_id)
        for volume_id in db.execute(
            select(LibraryVolumeFacet.volume_id).where(
                LibraryVolumeFacet.facet_id == facet_id
            )
        ).scalars()
    ]


def update_work_tags(
    db: Session, *, work_id: str, tags_json: str, now: datetime
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(tags=tags_json, updated_at=now)
    )


def update_work_author(
    db: Session,
    *,
    work_id: str,
    author: str,
    normalized_author: str,
    merge_key: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            author=author,
            normalized_author=normalized_author,
            merge_key=merge_key,
            updated_at=now,
        )
    )


def update_work_series_name(
    db: Session, *, work_id: str, series_name: str, now: datetime
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(series_name=series_name, updated_at=now)
    )


def clear_work_series(db: Session, *, work_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(series_name=None, series_index=None, updated_at=now)
    )


def update_volume_publisher(
    db: Session, *, volume_id: str, publisher: str, now: datetime
) -> None:
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(publisher=publisher, updated_at=now)
    )


def clear_volume_publisher(db: Session, *, volume_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.id == volume_id)
        .values(publisher=None, updated_at=now)
    )


def update_facet_aliases(
    db: Session, *, facet_id: str, aliases_json: str, now: datetime
) -> None:
    db.execute(
        update(LibraryFacet)
        .where(LibraryFacet.id == facet_id)
        .values(aliases=aliases_json, updated_at=now)
    )


def update_facet_name(
    db: Session,
    *,
    facet_id: str,
    name: str,
    normalized_name: str,
    aliases_json: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryFacet)
        .where(LibraryFacet.id == facet_id)
        .values(
            name=name,
            normalized_name=normalized_name,
            aliases=aliases_json,
            updated_at=now,
        )
    )


def delete_facets(db: Session, facet_ids: list[str]) -> None:
    if not facet_ids:
        return
    db.execute(delete(LibraryFacet).where(LibraryFacet.id.in_(facet_ids)))

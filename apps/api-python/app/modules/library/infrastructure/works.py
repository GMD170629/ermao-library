"""ORM persistence for work and media-version structure commands."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.shelf import ShelfWork

STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}


def entity_as_legacy_dict(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def get_visible_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.scalar(
        select(LibraryWork).where(
            LibraryWork.id == work_id,
            LibraryWork.hidden.is_(False),
        )
    )
    return entity_as_legacy_dict(work) if work is not None else None


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.get(LibraryWork, work_id)
    return entity_as_legacy_dict(work) if work is not None else None


def update_work_fields(
    db: Session, work_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    mapping = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(LibraryWork).mapper.column_attrs
    }
    payload = {mapping[key]: value for key, value in values.items() if key in mapping}
    if payload:
        result = db.execute(
            update(LibraryWork).where(LibraryWork.id == work_id).values(**payload)
        )
        if not result.rowcount:
            return None
        db.flush()
    return get_work(db, work_id)


def list_media_versions_for_works(
    db: Session, work_ids: list[str]
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.scalars(
        select(LibraryMediaVersion).where(LibraryMediaVersion.work_id.in_(work_ids))
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]


def list_progress_for_works(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(
        select(LibraryReadingProgress.id, LibraryMediaVersion.work_id)
        .join(LibraryVolume, LibraryVolume.id == LibraryReadingProgress.volume_id)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryMediaVersion.work_id.in_(work_ids))
    ).all()
    return [{"id": row.id, "workId": row.work_id} for row in rows]


def list_media_histories_for_works(
    db: Session, work_ids: list[str]
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    histories = db.scalars(
        select(UserMediaHistory)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == UserMediaHistory.media_version_id,
        )
        .where(LibraryMediaVersion.work_id.in_(work_ids))
    ).all()
    return [entity_as_legacy_dict(history) for history in histories]


def list_shelf_links_for_works(
    db: Session, work_ids: list[str]
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    links = db.scalars(select(ShelfWork).where(ShelfWork.work_id.in_(work_ids))).all()
    return [entity_as_legacy_dict(link) for link in links]


def update_merged_target_work(
    db: Session,
    *,
    work_id: str,
    tags_json: str,
    description: str | None,
    series_name: str | None,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            tags=tags_json,
            description=func.coalesce(
                func.nullif(LibraryWork.description, ""), description
            ),
            series_name=func.coalesce(
                func.nullif(LibraryWork.series_name, ""), series_name
            ),
            updated_at=now,
        )
    )


def move_media_version_to_work(
    db: Session,
    *,
    media_version_id: str,
    target_work_id: str,
    now: datetime,
) -> str:
    source = db.get(LibraryMediaVersion, media_version_id)
    if source is None:
        raise ValueError("媒介版本不存在")
    target = db.scalar(
        select(LibraryMediaVersion).where(
            LibraryMediaVersion.work_id == target_work_id,
            LibraryMediaVersion.media_kind == source.media_kind,
        )
    )
    if target is None:
        source.work_id = target_work_id
        source.updated_at = now
        return source.id
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.media_version_id == source.id)
        .values(media_version_id=target.id, updated_at=now)
    )
    for history in db.scalars(
        select(UserMediaHistory).where(UserMediaHistory.media_version_id == source.id)
    ).all():
        existing = db.scalar(
            select(UserMediaHistory).where(
                UserMediaHistory.user_id == history.user_id,
                UserMediaHistory.media_version_id == target.id,
            )
        )
        if existing is None:
            history.media_version_id = target.id
        elif history.updated_at > existing.updated_at:
            existing.last_volume_id = history.last_volume_id
            existing.updated_at = history.updated_at
            db.delete(history)
        else:
            db.delete(history)
    db.delete(source)
    return target.id


def list_shelf_ids_for_work(db: Session, work_id: str) -> list[str]:
    return [
        str(value)
        for value in db.scalars(
            select(ShelfWork.shelf_id).where(ShelfWork.work_id == work_id)
        )
    ]


def ensure_shelf_work_link(
    db: Session, *, shelf_id: str, work_id: str, now: datetime
) -> None:
    db.execute(
        sqlite_insert(ShelfWork)
        .values(shelf_id=shelf_id, work_id=work_id, created_at=now)
        .on_conflict_do_nothing(index_elements=[ShelfWork.shelf_id, ShelfWork.work_id])
    )


def transfer_source_work_side_effects(
    db: Session,
    *,
    source_work_id: str,
    target_work_id: str,
    now: datetime,
) -> None:
    for shelf_id in list_shelf_ids_for_work(db, source_work_id):
        ensure_shelf_work_link(db, shelf_id=shelf_id, work_id=target_work_id, now=now)
    db.execute(delete(ShelfWork).where(ShelfWork.work_id == source_work_id))
    db.execute(delete(LibraryWork).where(LibraryWork.id == source_work_id))


def list_duplicate_identity_groups(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
            func.count(LibraryWork.id).label("count"),
        )
        .where(LibraryWork.hidden.is_(False))
        .group_by(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
        )
        .having(func.count(LibraryWork.id) > 1)
    ).all()
    return [
        {
            "normalizedTitle": row.normalized_title,
            "normalizedAuthor": row.normalized_author,
            "count": int(row.count),
        }
        for row in rows
    ]


def list_works_for_normalized_identity(
    db: Session, *, normalized_title: str, normalized_author: str
) -> list[dict[str, Any]]:
    works = db.scalars(
        select(LibraryWork).where(
            LibraryWork.normalized_title == normalized_title,
            LibraryWork.normalized_author == normalized_author,
            LibraryWork.hidden.is_(False),
        )
    ).all()
    return [entity_as_legacy_dict(work) for work in works]

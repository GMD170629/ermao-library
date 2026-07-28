"""ORM persistence for library work merge/split and duplicate queries."""

from __future__ import annotations

from datetime import datetime
from time import time_ns
from typing import Any

from sqlalchemy import delete, func, insert, inspect as sa_inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, edition_visibility_predicate
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryReadingProgress,
    LibraryWork,
)
from app.models.shelf import ShelfWork
from app.models.settings import ReaderProgressCursor

STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}


def entity_as_legacy_dict(entity: object) -> dict[str, Any]:
    """Map an ORM entity to camelCase keys matching legacy raw-SQL row dicts."""

    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key)
        for prop in mapper.column_attrs
    }


def get_visible_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.execute(
        select(LibraryWork).where(
            LibraryWork.id == work_id,
            func.coalesce(LibraryWork.hidden, 0) == 0,
        )
    ).scalar_one_or_none()
    return entity_as_legacy_dict(work) if work is not None else None


def list_editions_for_works(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(select(LibraryEdition).where(LibraryEdition.work_id.in_(work_ids))).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]


def list_progress_for_works(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(
        select(LibraryReadingProgress.id, LibraryReadingProgress.work_id).where(
            LibraryReadingProgress.work_id.in_(work_ids)
        )
    ).all()
    return [{"id": row.id, "workId": row.work_id} for row in rows]


def list_consumption_for_works(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(
        select(LibraryConsumptionState).where(LibraryConsumptionState.work_id.in_(work_ids))
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]


def list_shelf_links_for_works(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(select(ShelfWork).where(ShelfWork.work_id.in_(work_ids))).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]


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
            description=func.coalesce(func.nullif(LibraryWork.description, ""), description),
            series_name=func.coalesce(func.nullif(LibraryWork.series_name, ""), series_name),
            updated_at=now,
        )
    )


def reassign_edition_to_work(
    db: Session,
    *,
    edition_id: str,
    target_work_id: str,
    version_key: str,
    primary: bool,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == edition_id)
        .values(
            work_id=target_work_id,
            version_key=version_key,
            is_primary=primary,
            updated_at=now,
        )
    )


def reassign_progress_work_id(
    db: Session,
    *,
    source_work_id: str,
    target_work_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.work_id == source_work_id)
        .values(work_id=target_work_id, updated_at=now)
    )


def list_consumption_for_work(db: Session, work_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryConsumptionState).where(LibraryConsumptionState.work_id == work_id)
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]


def get_consumption_for_user_work_media(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    media_kind: str,
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryConsumptionState).where(
            LibraryConsumptionState.user_id == user_id,
            LibraryConsumptionState.work_id == work_id,
            LibraryConsumptionState.media_kind == media_kind,
        )
    ).scalar_one_or_none()
    return entity_as_legacy_dict(row) if row is not None else None


def merge_consumption_state_into_existing(
    db: Session,
    *,
    existing: dict[str, Any],
    source: dict[str, Any],
    now: datetime,
) -> None:
    source_rank = STATUS_RANK.get(str(source.get("status") or "UNREAD"), 0)
    target_rank = STATUS_RANK.get(str(existing.get("status") or "UNREAD"), 0)
    newer_source = str(source.get("updatedAt") or "") > str(existing.get("updatedAt") or "")
    db.execute(
        update(LibraryConsumptionState)
        .where(LibraryConsumptionState.id == str(existing["id"]))
        .values(
            status=source.get("status") if source_rank > target_rank else existing.get("status"),
            last_edition_id=(
                source.get("lastEditionId") if newer_source else existing.get("lastEditionId")
            ),
            last_volume_id=(
                source.get("lastVolumeId") if newer_source else existing.get("lastVolumeId")
            ),
            last_unit_id=source.get("lastUnitId") if newer_source else existing.get("lastUnitId"),
            updated_at=now,
        )
    )
    db.execute(delete(LibraryConsumptionState).where(LibraryConsumptionState.id == str(source["id"])))


def reassign_consumption_work_id(
    db: Session,
    *,
    consumption_id: str,
    target_work_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryConsumptionState)
        .where(LibraryConsumptionState.id == consumption_id)
        .values(work_id=target_work_id, updated_at=now)
    )


def list_shelf_ids_for_work(db: Session, work_id: str) -> list[str]:
    return [
        str(shelf_id)
        for shelf_id in db.execute(
            select(ShelfWork.shelf_id).where(ShelfWork.work_id == work_id)
        ).scalars()
    ]


def ensure_shelf_work_link(
    db: Session,
    *,
    shelf_id: str,
    work_id: str,
    now: datetime,
) -> None:
    db.execute(
        sqlite_insert(ShelfWork)
        .values(shelf_id=shelf_id, work_id=work_id, created_at=now)
        .on_conflict_do_nothing(index_elements=[ShelfWork.shelf_id, ShelfWork.work_id])
    )


def delete_shelf_links_for_work(db: Session, work_id: str) -> None:
    db.execute(delete(ShelfWork).where(ShelfWork.work_id == work_id))


def hide_merged_source_work(db: Session, *, work_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(hidden=True, organize_status="APPLIED", updated_at=now)
    )


def select_preferred_edition(db: Session, work_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryEdition.id, LibraryEdition.format)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
        .order_by(
            func.coalesce(LibraryEdition.is_primary, 0).desc(),
            LibraryEdition.created_at.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return {"id": row.id, "format": row.format}


def set_work_primary_edition(
    db: Session,
    *,
    work_id: str,
    edition_id: str,
    work_type: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(primary_edition_id=edition_id, work_type=work_type, updated_at=now)
    )


def transfer_source_work_side_effects(
    db: Session,
    *,
    source_work_id: str,
    target_work_id: str,
    now: datetime,
) -> None:
    """Move progress, consumption, and shelf links from a source work onto the target."""

    reassign_progress_work_id(
        db,
        source_work_id=source_work_id,
        target_work_id=target_work_id,
        now=now,
    )
    for state in list_consumption_for_work(db, source_work_id):
        existing = get_consumption_for_user_work_media(
            db,
            user_id=str(state["userId"]),
            work_id=target_work_id,
            media_kind=str(state["mediaKind"]),
        )
        if existing:
            merge_consumption_state_into_existing(db, existing=existing, source=state, now=now)
        else:
            reassign_consumption_work_id(
                db,
                consumption_id=str(state["id"]),
                target_work_id=target_work_id,
                now=now,
            )

    for shelf_id in list_shelf_ids_for_work(db, source_work_id):
        ensure_shelf_work_link(db, shelf_id=shelf_id, work_id=target_work_id, now=now)
    delete_shelf_links_for_work(db, source_work_id)
    hide_merged_source_work(db, work_id=source_work_id, now=now)


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.get(LibraryWork, work_id)
    return entity_as_legacy_dict(work) if work is not None else None


def update_work_fields(
    db: Session,
    work_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    mapping = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(LibraryWork).mapper.column_attrs
    }
    payload = {
        mapping[key]: value
        for key, value in values.items()
        if key in mapping
    }
    if payload:
        result = db.execute(
            update(LibraryWork)
            .where(LibraryWork.id == work_id)
            .values(**payload)
        )
        if not result.rowcount:
            return None
        db.flush()
    return get_work(db, work_id)


def update_edition_fields(
    db: Session,
    edition_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    mapping = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(LibraryEdition).mapper.column_attrs
    }
    payload = {
        mapping[key]: value
        for key, value in values.items()
        if key in mapping
    }
    result = db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == edition_id)
        .values(**payload)
    )
    if not result.rowcount:
        return None
    db.flush()
    from app.modules.library.infrastructure.projections import get_edition

    return get_edition(db, edition_id)


def get_visible_edition_for_work(
    db: Session,
    *,
    edition_id: str,
    work_id: str,
) -> dict[str, Any] | None:
    edition = db.execute(
        select(LibraryEdition).where(
            LibraryEdition.id == edition_id,
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, 0) == 0,
        )
    ).scalar_one_or_none()
    return entity_as_legacy_dict(edition) if edition is not None else None


def list_visible_editions_for_work(
    db: Session,
    *,
    work_id: str,
    context: AuthorizationContext | None = None,
) -> list[dict[str, Any]]:
    filters: list[Any] = [
        LibraryEdition.work_id == work_id,
        func.coalesce(LibraryEdition.hidden, 0) == 0,
    ]
    if context is not None:
        filters.append(edition_visibility_predicate(context))
    rows = db.scalars(
        select(LibraryEdition)
        .where(*filters)
        .order_by(
            func.coalesce(LibraryEdition.is_primary, 0).desc(),
            LibraryEdition.created_at.asc(),
        )
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]


def clear_reading_state_for_work(
    db: Session,
    *,
    user_id: str,
    work_id: str,
) -> None:
    db.execute(
        delete(LibraryReadingProgress).where(
            LibraryReadingProgress.user_id == user_id,
            LibraryReadingProgress.work_id == work_id,
        )
    )
    db.execute(
        delete(ReaderProgressCursor).where(
            ReaderProgressCursor.user_id == user_id,
            ReaderProgressCursor.work_id == work_id,
        )
    )
    db.execute(
        delete(LibraryConsumptionState).where(
            LibraryConsumptionState.user_id == user_id,
            LibraryConsumptionState.work_id == work_id,
        )
    )
    db.flush()


def mark_edition_finished(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    edition: dict[str, Any],
    reader_type: str,
    now: datetime,
) -> None:
    edition_id = str(edition["id"])
    progress_id = db.scalar(
        select(LibraryReadingProgress.id).where(
            LibraryReadingProgress.user_id == user_id,
            LibraryReadingProgress.work_id == work_id,
            LibraryReadingProgress.edition_id == edition_id,
            LibraryReadingProgress.volume_id.is_(None),
        )
    )
    if progress_id is None:
        db.execute(
            insert(LibraryReadingProgress.__table__).values(
                {
                    LibraryReadingProgress.id: f"bulk_progress_{time_ns()}",
                    LibraryReadingProgress.user_id: user_id,
                    LibraryReadingProgress.work_id: work_id,
                    LibraryReadingProgress.edition_id: edition_id,
                    LibraryReadingProgress.volume_id: None,
                    LibraryReadingProgress.reader_type: reader_type,
                    LibraryReadingProgress.position: "100",
                    LibraryReadingProgress.page: edition.get("pageCount")
                    or edition.get("chapterCount"),
                    LibraryReadingProgress.percent: 100,
                    LibraryReadingProgress.extra: "{}",
                    LibraryReadingProgress.schema_version: 2,
                    LibraryReadingProgress.created_at: now,
                    LibraryReadingProgress.updated_at: now,
                }
            )
        )
    else:
        db.execute(
            update(LibraryReadingProgress)
            .where(LibraryReadingProgress.id == progress_id)
            .values(percent=100, updated_at=now)
        )
    db.flush()


def clear_primary_for_media_kind(
    db: Session,
    *,
    work_id: str,
    media_kind: str,
    formats: tuple[str, ...] | None,
    now: datetime,
    has_media_kind_column: bool,
) -> None:
    filters = [LibraryEdition.work_id == work_id]
    if has_media_kind_column:
        # Match COALESCE(NULLIF(TRIM(mediaKind), ''), CASE format ...) = media_kind
        from sqlalchemy import case

        derived = func.coalesce(
            func.nullif(func.trim(LibraryEdition.media_kind), ""),
            case(
                (func.upper(LibraryEdition.format) == "COMIC", "COMIC"),
                (func.upper(LibraryEdition.format) == "AUDIO", "AUDIOBOOK"),
                else_="EBOOK",
            ),
        )
        filters.append(derived == media_kind)
    elif formats:
        filters.append(LibraryEdition.format.in_(formats))
    db.execute(
        update(LibraryEdition)
        .where(*filters)
        .values(is_primary=False, updated_at=now)
    )


def mark_edition_primary_for_work(
    db: Session,
    *,
    work_id: str,
    edition_id: str,
    work_type: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryEdition)
        .where(
            LibraryEdition.id == edition_id,
            LibraryEdition.work_id == work_id,
        )
        .values(is_primary=True, updated_at=now)
    )
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            primary_edition_id=edition_id,
            work_type=work_type,
            updated_at=now,
        )
    )


def count_visible_editions(db: Session, work_id: str) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(LibraryEdition)
            .where(
                LibraryEdition.work_id == work_id,
                func.coalesce(LibraryEdition.hidden, 0) == 0,
            )
        ).scalar()
        or 0
    )


def list_progress_work_ids_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryReadingProgress.id, LibraryReadingProgress.work_id).where(
            LibraryReadingProgress.edition_id == edition_id
        )
    ).all()
    return [{"id": row.id, "workId": row.work_id} for row in rows]


def insert_work_row(db: Session, row: dict[str, Any]) -> None:
    mapper = sa_inspect(LibraryWork)
    name_to_key = {prop.columns[0].name: prop.key for prop in mapper.column_attrs}
    values = {name_to_key[name]: value for name, value in row.items() if name in name_to_key}
    if not values:
        return
    db.execute(sqlite_insert(LibraryWork).values(**values))


def move_edition_to_new_work_as_primary(
    db: Session,
    *,
    edition_id: str,
    new_work_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == edition_id)
        .values(work_id=new_work_id, is_primary=True, updated_at=now)
    )


def reassign_progress_by_edition(
    db: Session,
    *,
    edition_id: str,
    new_work_id: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.edition_id == edition_id)
        .values(work_id=new_work_id, updated_at=now)
    )


def mark_edition_primary(db: Session, *, edition_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == edition_id)
        .values(is_primary=True, updated_at=now)
    )


def list_duplicate_identity_groups(db: Session) -> list[dict[str, Any]]:
    title = LibraryWork.normalized_title
    author = func.coalesce(LibraryWork.normalized_author, "")
    rows = db.execute(
        select(
            title.label("normalizedTitle"),
            author.label("normalizedAuthor"),
            func.count().label("count"),
        )
        .where(
            func.coalesce(LibraryWork.hidden, 0) == 0,
            func.trim(func.coalesce(LibraryWork.normalized_title, "")) != "",
        )
        .group_by(title, author)
        .having(func.count() > 1)
        .order_by(func.count().desc(), func.max(LibraryWork.updated_at).desc())
    ).all()
    return [
        {
            "normalizedTitle": row.normalizedTitle,
            "normalizedAuthor": row.normalizedAuthor,
            "count": int(row.count),
        }
        for row in rows
    ]


def list_works_for_normalized_identity(
    db: Session,
    *,
    normalized_title: str,
    normalized_author: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryWork)
        .where(
            func.coalesce(LibraryWork.hidden, 0) == 0,
            LibraryWork.normalized_title == normalized_title,
            func.coalesce(LibraryWork.normalized_author, "") == normalized_author,
        )
        .order_by(LibraryWork.updated_at.desc(), LibraryWork.created_at.asc())
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]

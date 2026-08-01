"""ORM queries for reader v2 routes."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import Table, delete, func, inspect as sa_inspect, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    edition_visibility_predicate,
    monitor_folder_visibility_predicate,
)
from app.db.base import Base
from app.models.auth import ReaderBookmark
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
from app.models.settings import ReaderBookPreference, ReaderPreference, ReaderProgressCursor
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def _legacy_values(model: type, values: dict[str, Any]) -> dict[str, Any]:
    name_to_attr = _legacy_column_to_attr(model)
    return {
        name_to_attr[key]: value
        for key, value in values.items()
        if key in name_to_attr
    }


def has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.connection()).has_table(table)


def table_columns(db: Session, table: str) -> set[str]:
    inspector = sa_inspect(db.connection())
    if not inspector.has_table(table):
        return set()
    return {
        str(column["name"])
        for column in inspector.get_columns(table)
    }


def _legacy_table(db: Session, table: str) -> Table | None:
    if not has_table(db, table):
        return None
    return Base.metadata.tables.get(table)


def _legacy_rows(stmt) -> list[dict[str, Any]]:
    return [dict(row) for row in stmt.mappings().all()]


def _select_existing(db: Session, table: Table):
    existing = table_columns(db, table.name)
    return select(*(column for column in table.c if column.name in existing))


def get_edition(db: Session, edition_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryEdition")
    if table is None:
        return None
    row = db.execute(_select_existing(db, table).where(table.c.id == edition_id)).mappings().first()
    return dict(row) if row else None


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryWork")
    if table is None:
        return None
    row = db.execute(_select_existing(db, table).where(table.c.id == work_id)).mappings().first()
    return dict(row) if row else None


def get_volume(db: Session, volume_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return None
    row = db.execute(_select_existing(db, table).where(table.c.id == volume_id)).mappings().first()
    return dict(row) if row else None


def get_edition_work_id(db: Session, edition_id: str) -> str | None:
    table = _legacy_table(db, "LibraryEdition")
    if table is None:
        return None
    return db.scalar(select(table.c.workId).where(table.c.id == edition_id))


def list_volume_ids_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return []
    rows = db.execute(
        select(table.c.id)
        .where(table.c.editionId == edition_id)
        .order_by(table.c.sortOrder, table.c.id)
    ).all()
    return [{"id": row.id} for row in rows]


def list_volumes_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return []
    return _legacy_rows(
        db.execute(
            _select_existing(db, table)
            .where(table.c.editionId == edition_id)
            .order_by(table.c.sortOrder, table.c.id)
        )
    )


def list_progress_for_user_work(db: Session, user_id: str, work_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryReadingProgress")
    if table is None:
        return []
    return _legacy_rows(
        db.execute(
            _select_existing(db, table)
            .where(table.c.userId == user_id, table.c.workId == work_id)
            .order_by(table.c.updatedAt.desc(), table.c.id.desc())
        )
    )


def list_units_for_edition(
    db: Session,
    edition_id: str,
    unit_type: str,
    volume_id: str | None = None,
) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryReadingUnit")
    if table is None:
        return []
    filters = [table.c.editionId == edition_id, func.lower(table.c.unitType) == unit_type.lower()]
    if volume_id:
        filters.append(table.c.volumeId == volume_id)
    return _legacy_rows(
        db.execute(_select_existing(db, table).where(*filters).order_by(table.c.sortOrder, table.c.id))
    )


def list_files_for_edition(
    db: Session,
    edition_id: str,
    volume_id: str | None = None,
) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryFile")
    if table is None:
        return []
    filters = [table.c.editionId == edition_id]
    if volume_id:
        filters.append(table.c.volumeId == volume_id)
    return _legacy_rows(
        db.execute(_select_existing(db, table).where(*filters).order_by(table.c.sortOrder, table.c.id))
    )


def get_audio_manifest_raw_json(db: Session, edition_id: str) -> dict[str, Any] | None:
    return get_edition_metadata_raw_json(db, edition_id, "audiobook_manifest")


def get_edition_metadata_raw_json(
    db: Session, edition_id: str, source: str
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryMetadata")
    if table is None:
        return None
    row = db.execute(
        select(table.c.rawJson)
        .where(table.c.editionId == edition_id, table.c.source == source)
        .order_by(table.c.createdAt.desc())
        .limit(1)
    ).first()
    return {"rawJson": row.rawJson} if row is not None else None


def list_reader_preferences(db: Session, user_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "ReaderPreference")
    if table is None:
        return []
    return _legacy_rows(db.execute(_select_existing(db, table).where(table.c.userId == user_id)))


def get_book_preference(db: Session, user_id: str, work_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "ReaderBookPreference")
    if table is None:
        return None
    row = db.execute(
        _select_existing(db, table).where(table.c.userId == user_id, table.c.workId == work_id)
    ).mappings().first()
    return dict(row) if row else None


def update_book_preference(
    db: Session,
    preference_id: str,
    *,
    schema_version: int,
    preferences: str,
    updated_at: object,
) -> None:
    table = _legacy_table(db, "ReaderBookPreference")
    if table is None:
        return
    db.execute(
        update(table)
        .where(table.c.id == preference_id)
        .values(
            schemaVersion=schema_version,
            preferences=preferences,
            # Canonicalizing an already stored payload is a compatibility repair,
            # not a user preference change. Supplying the current value prevents
            # the mapped column's on-update timestamp from changing observable
            # reader state.
            updatedAt=updated_at,
        )
    )


def insert_book_preference(db: Session, values: dict[str, Any]) -> None:
    table = _legacy_table(db, "ReaderBookPreference")
    if table is None:
        return
    payload = {key: value for key, value in values.items() if key in table.c}
    if not payload:
        return
    db.execute(sqlite_insert(table).values(**payload))


def get_consumption_state(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    media_kind: str,
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryConsumptionState")
    if table is None:
        return None
    row = db.execute(
        _select_existing(db, table).where(
            table.c.userId == user_id,
            table.c.workId == work_id,
            table.c.mediaKind == media_kind,
        )
    ).mappings().first()
    return dict(row) if row else None


def update_consumption_state(db: Session, row_id: str, values: dict[str, Any]) -> None:
    name_to_attr = _legacy_column_to_attr(LibraryConsumptionState)
    payload = {name_to_attr[key]: value for key, value in values.items() if key in name_to_attr}
    db.execute(update(LibraryConsumptionState).where(LibraryConsumptionState.id == row_id).values(**payload))


def insert_consumption_state(db: Session, values: dict[str, Any]) -> None:
    db.add(LibraryConsumptionState(**_legacy_values(LibraryConsumptionState, values)))


def list_visible_editions_for_work(
    db: Session,
    work_id: str,
    context: AuthorizationContext,
) -> list[dict[str, Any]]:
    edition_table = _legacy_table(db, "LibraryEdition")
    if edition_table is None:
        return []
    filters = [
        edition_table.c.workId == work_id,
        func.coalesce(edition_table.c.hidden, False).is_(False),
    ]
    if context.is_admin:
        filters.append(edition_table.c.id.is_not(None))
    elif "monitorFolderId" in edition_table.c:
        filters.append(
            monitor_folder_visibility_predicate(context, edition_table.c.monitorFolderId)
        )
    else:
        filters.append(edition_visibility_predicate(context))
    order_by = [edition_table.c.createdAt, edition_table.c.id]
    if "isPrimary" in edition_table.c:
        order_by = [func.coalesce(edition_table.c.isPrimary, False).desc(), *order_by]
    return _legacy_rows(db.execute(select(edition_table).where(*filters).order_by(*order_by)))


def list_visible_volumes_for_work(
    db: Session,
    work_id: str,
    edition_ids: list[str],
) -> list[dict[str, Any]]:
    if not edition_ids:
        return []
    volume_table = _legacy_table(db, "LibraryVolume")
    edition_table = _legacy_table(db, "LibraryEdition")
    if volume_table is None or edition_table is None:
        return []
    return _legacy_rows(
        db.execute(
            select(volume_table)
            .join(edition_table, edition_table.c.id == volume_table.c.editionId)
            .where(
                edition_table.c.workId == work_id,
                func.coalesce(edition_table.c.hidden, False).is_(False),
                edition_table.c.id.in_(edition_ids),
            )
            .order_by(edition_table.c.createdAt, volume_table.c.sortOrder, volume_table.c.id)
        )
    )


def list_bookmarks(
    db: Session,
    *,
    user_id: str,
    edition_id: str,
    content_fingerprint: str,
) -> list[dict[str, Any]]:
    table = _legacy_table(db, "ReaderBookmark")
    if table is None:
        return []
    return _legacy_rows(
        db.execute(
            _select_existing(db, table)
            .where(
                table.c.userId == user_id,
                table.c.editionId == edition_id,
                table.c.contentFingerprint == content_fingerprint,
            )
            .order_by(table.c.percent, table.c.bookmarkCreatedAt, table.c.bookmarkId)
        )
    )


def replace_bookmarks(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    edition_id: str,
    content_fingerprint: str,
    bookmarks: list[dict[str, Any]],
    now: datetime,
) -> None:
    db.execute(
        delete(ReaderBookmark).where(
            ReaderBookmark.user_id == user_id,
            ReaderBookmark.edition_id == edition_id,
            ReaderBookmark.content_fingerprint == content_fingerprint,
        )
    )
    for index, bookmark in enumerate(bookmarks):
        db.add(
            ReaderBookmark(
                id=bookmark["id"],
                user_id=user_id,
                work_id=work_id,
                edition_id=edition_id,
                content_fingerprint=content_fingerprint,
                bookmark_id=bookmark["bookmark_id"],
                location_json=bookmark["location_json"],
                label=bookmark["label"],
                percent=bookmark["percent"],
                bookmark_created_at=bookmark["bookmark_created_at"],
                created_at=now,
                updated_at=now,
            )
        )


def get_reading_unit(
    db: Session,
    *,
    chapter_id: str,
    edition_id: str,
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryReadingUnit")
    if table is None:
        return None
    row = db.execute(
        select(table.c.id, table.c.fileId).where(
            table.c.id == chapter_id,
            table.c.editionId == edition_id,
        )
    ).first()
    if row is None:
        return None
    return {"id": row.id, "fileId": row.fileId}


def max_client_sequence(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    client_id: str,
) -> int | None:
    table = _legacy_table(db, "LibraryReadingProgress")
    if table is None or "clientSequence" not in table.c:
        return None
    return db.scalar(
        select(func.max(table.c.clientSequence)).where(
            table.c.userId == user_id,
            table.c.workId == work_id,
            table.c.clientId == client_id,
        )
    )


def seed_progress_cursor(
    db: Session,
    *,
    cursor_id: str,
    user_id: str,
    work_id: str,
    client_id: str,
    high_water: int,
    now: datetime,
) -> None:
    db.execute(
        sqlite_insert(ReaderProgressCursor)
        .values(
            id=cursor_id,
            user_id=user_id,
            work_id=work_id,
            client_id=client_id,
            high_water=high_water,
            last_mutation_id=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ReaderProgressCursor.user_id,
                ReaderProgressCursor.work_id,
                ReaderProgressCursor.client_id,
            ]
        )
    )


def claim_client_sequence(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    client_id: str,
    client_sequence: int,
    mutation_id: str,
    now: datetime,
) -> bool:
    initial_high_water = -1
    if {"clientId", "clientSequence"}.issubset(table_columns(db, "LibraryReadingProgress")):
        stored = max_client_sequence(db, user_id=user_id, work_id=work_id, client_id=client_id)
        if stored is not None:
            initial_high_water = int(stored)

    key = f"{user_id}\0{work_id}\0{client_id}"
    seed_progress_cursor(
        db,
        cursor_id=f"cursor_{hashlib.sha1(key.encode('utf-8')).hexdigest()}",
        user_id=user_id,
        work_id=work_id,
        client_id=client_id,
        high_water=initial_high_water,
        now=now,
    )

    result = db.execute(
        update(ReaderProgressCursor)
        .where(
            ReaderProgressCursor.user_id == user_id,
            ReaderProgressCursor.work_id == work_id,
            ReaderProgressCursor.client_id == client_id,
            ReaderProgressCursor.high_water < client_sequence,
        )
        .values(
            high_water=client_sequence,
            last_mutation_id=mutation_id,
            updated_at=now,
        )
    )
    return int(result.rowcount or 0) == 1


def get_reading_progress(
    db: Session,
    *,
    user_id: str,
    edition_id: str,
    volume_id: str | None,
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryReadingProgress")
    if table is None:
        return None
    filters = [table.c.userId == user_id, table.c.editionId == edition_id]
    if volume_id:
        filters.append(table.c.volumeId == volume_id)
    else:
        filters.append(table.c.volumeId.is_(None))
    row = db.execute(_select_existing(db, table).where(*filters)).mappings().first()
    return dict(row) if row else None


def upsert_reading_progress(
    db: Session,
    *,
    existing_id: str | None,
    values: dict[str, Any],
    insert_values: dict[str, Any],
) -> None:
    table = _legacy_table(db, "LibraryReadingProgress")
    if table is None:
        return
    if existing_id:
        payload = {key: value for key, value in values.items() if key in table.c}
        if payload:
            db.execute(update(table).where(table.c.id == existing_id).values(**payload))
        return
    payload = {key: value for key, value in insert_values.items() if key in table.c}
    if payload:
        db.execute(insert(table).values(**payload))


def list_progress_volume_percents(
    db: Session,
    *,
    user_id: str,
    edition_id: str,
) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryReadingProgress")
    if table is None:
        return []
    rows = db.execute(
        select(table.c.volumeId, table.c.percent).where(
            table.c.userId == user_id,
            table.c.editionId == edition_id,
        )
    ).all()
    return [{"volumeId": row.volumeId, "percent": row.percent} for row in rows]

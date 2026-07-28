"""ORM persistence for library undoable operations and snapshot restore."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from time import time_ns
from typing import Any

from sqlalchemy import delete, inspect as sa_inspect, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryEditionFacet,
    LibraryFacet,
    LibraryOperation,
    LibraryReadingProgress,
    LibraryWork,
    LibraryWorkFacet,
)
from app.models.shelf import ShelfWork
from app.modules.library.infrastructure.works import entity_as_legacy_dict

WORK_RESTORE_COLUMNS = {
    "monitorFolderId",
    "origin",
    "title",
    "normalizedTitle",
    "author",
    "normalizedAuthor",
    "description",
    "workType",
    "status",
    "publicationStatus",
    "trackingStatus",
    "localLatestVolume",
    "localLatestChapter",
    "localLatestTitle",
    "localLatestAt",
    "tags",
    "seriesName",
    "seriesIndex",
    "publishedYear",
    "metadataQuality",
    "organizeStatus",
    "coverPath",
    "coverStatus",
    "hidden",
    "organized",
    "primaryEditionId",
    "mergeKey",
    "updatedAt",
}
EDITION_RESTORE_COLUMNS = {
    "workId",
    "monitorFolderId",
    "origin",
    "mediaKind",
    "format",
    "versionName",
    "versionKey",
    "sourceGroupKey",
    "description",
    "language",
    "publisher",
    "publishedAt",
    "identifier",
    "isbn",
    "importStatus",
    "importError",
    "sizeBytes",
    "pageCount",
    "chapterCount",
    "durationMs",
    "trackCount",
    "narrator",
    "abridged",
    "coverPath",
    "coverStatus",
    "primary",
    "hidden",
    "updatedAt",
}
FACET_RESTORE_COLUMNS = {"name", "normalizedName", "aliases", "updatedAt"}

_SNAPSHOT_MODELS: dict[str, type] = {
    "LibraryWork": LibraryWork,
    "LibraryEdition": LibraryEdition,
    "LibraryFacet": LibraryFacet,
    "LibraryWorkFacet": LibraryWorkFacet,
    "LibraryEditionFacet": LibraryEditionFacet,
    "ShelfWork": ShelfWork,
    "LibraryConsumptionState": LibraryConsumptionState,
}


def has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.connection()).has_table(table)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _column_name_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def legacy_row_to_attr_values(
    model: type,
    row: dict[str, Any],
    *,
    columns: set[str] | None = None,
) -> dict[str, Any]:
    name_to_key = _column_name_to_attr(model)
    values: dict[str, Any] = {}
    for name, value in row.items():
        if columns is not None and name not in columns:
            continue
        key = name_to_key.get(name)
        if key is not None:
            values[key] = value
    return values


def create_operation(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    summary: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    operation_id = f"op_{time_ns()}"
    expires_at = now + timedelta(days=7)
    if not has_table(db, "LibraryOperation"):
        return {
            "id": operation_id,
            "action": action,
            "status": "COMPLETED",
            "summary": summary,
            "expiresAt": expires_at.isoformat(),
            "undoAvailable": False,
        }
    db.add(
        LibraryOperation(
            id=operation_id,
            user_id=user_id,
            action=action,
            status="COMPLETED",
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            payload_json=_json(payload),
            inverse_json=_json(inverse),
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    return {
        "id": operation_id,
        "action": action,
        "status": "COMPLETED",
        "summary": summary,
        "expiresAt": expires_at.isoformat(),
        "undoAvailable": True,
    }


def get_operation(db: Session, operation_id: str) -> dict[str, Any] | None:
    operation = db.get(LibraryOperation, operation_id)
    return entity_as_legacy_dict(operation) if operation is not None else None


def list_operations_for_user(
    db: Session,
    user_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LibraryOperation)
        .where(
            or_(
                LibraryOperation.user_id == user_id,
                LibraryOperation.user_id.is_(None),
            )
        )
        .order_by(LibraryOperation.created_at.desc(), LibraryOperation.id.desc())
        .limit(limit)
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]


def mark_operation_undone(db: Session, *, operation_id: str, now: datetime) -> None:
    db.execute(
        update(LibraryOperation)
        .where(LibraryOperation.id == operation_id)
        .values(status="UNDONE", undone_at=now, updated_at=now)
    )


def insert_snapshot(db: Session, table: str, row: dict[str, Any]) -> None:
    if not row:
        return
    model = _SNAPSHOT_MODELS.get(table)
    if model is None:
        raise ValueError(f"Unsupported snapshot table: {table}")
    values = legacy_row_to_attr_values(model, row)
    if not values:
        return
    primary_key = list(sa_inspect(model).primary_key)
    pk_attr_keys = {column.key for column in primary_key}
    stmt = sqlite_insert(model).values(**values)
    update_set = {
        getattr(model, key): value
        for key, value in values.items()
        if key not in pk_attr_keys
    }
    if update_set:
        stmt = stmt.on_conflict_do_update(index_elements=primary_key, set_=update_set)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=primary_key)
    db.execute(stmt)


def restore_work_row(db: Session, work_id: str, row: dict[str, Any]) -> None:
    filtered = legacy_row_to_attr_values(LibraryWork, row, columns=WORK_RESTORE_COLUMNS)
    if not filtered:
        return
    db.execute(update(LibraryWork).where(LibraryWork.id == work_id).values(**filtered))


def restore_edition_row(db: Session, edition_id: str, row: dict[str, Any]) -> None:
    filtered = legacy_row_to_attr_values(LibraryEdition, row, columns=EDITION_RESTORE_COLUMNS)
    if not filtered:
        return
    db.execute(update(LibraryEdition).where(LibraryEdition.id == edition_id).values(**filtered))


def restore_facet_row(db: Session, facet_id: str, row: dict[str, Any]) -> None:
    filtered = legacy_row_to_attr_values(LibraryFacet, row, columns=FACET_RESTORE_COLUMNS)
    if not filtered:
        return
    db.execute(update(LibraryFacet).where(LibraryFacet.id == facet_id).values(**filtered))


def delete_shelf_work_link(db: Session, *, shelf_id: str, work_id: str) -> None:
    db.execute(
        delete(ShelfWork).where(ShelfWork.shelf_id == shelf_id, ShelfWork.work_id == work_id)
    )


def delete_consumption_by_id(db: Session, consumption_id: str) -> None:
    db.execute(delete(LibraryConsumptionState).where(LibraryConsumptionState.id == consumption_id))


def reassign_progress_work_id_by_id(db: Session, *, progress_id: str, work_id: str) -> None:
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.id == progress_id)
        .values(work_id=work_id)
    )


def clear_edition_primary(db: Session, edition_id: str) -> None:
    db.execute(
        update(LibraryEdition).where(LibraryEdition.id == edition_id).values(is_primary=False)
    )


def delete_work(db: Session, work_id: str) -> None:
    db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))


def delete_work_facets_for_work(db: Session, work_id: str) -> None:
    db.execute(delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id))


def delete_edition_facets_for_edition(db: Session, edition_id: str) -> None:
    db.execute(delete(LibraryEditionFacet).where(LibraryEditionFacet.edition_id == edition_id))

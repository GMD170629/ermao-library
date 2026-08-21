"""ORM persistence for library metadata operation snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import time_ns
from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import (
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryOperation,
    LibraryReadableResourceFacet,
    LibraryReadableResourceMetadata,
)
from app.modules.library.application.resource_commands import OperationSummary
from app.modules.library.infrastructure.books import entity_record

_SNAPSHOT_MODELS: dict[str, type] = {
    model.__tablename__: model
    for model in (
        LibraryFacet,
        LibraryBookFacet,
        LibraryReadableResourceFacet,
    )
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(frozen=True, slots=True)
class PreparedOperationWrite:
    row: dict[str, Any]
    record: dict[str, Any]


def prepare_operation_write(
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    summary: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
    now: datetime,
    undoable: bool = True,
) -> PreparedOperationWrite:
    operation_id = f"op_{time_ns()}"
    expires_at = now + timedelta(days=7)
    status = "COMPLETED" if undoable else "FINALIZED"
    payload_json = _json(payload)
    inverse_json = _json(inverse)
    return PreparedOperationWrite(
        row={
            "id": operation_id,
            "user_id": user_id,
            "action": action,
            "status": status,
            "target_type": target_type,
            "target_id": target_id,
            "summary": summary,
            "payload_json": payload_json,
            "inverse_json": inverse_json,
            "expires_at": expires_at if undoable else None,
            "created_at": now,
            "updated_at": now,
        },
        record={
            "id": operation_id,
            "userId": user_id,
            "action": action,
            "status": status,
            "targetType": target_type,
            "targetId": target_id,
            "summary": summary,
            "payloadJson": payload_json,
            "inverseJson": inverse_json,
            "expiresAt": expires_at if undoable else None,
            "createdAt": now,
            "updatedAt": now,
        },
    )


def write_prepared_operation(db: Session, prepared: PreparedOperationWrite) -> None:
    db.execute(insert(LibraryOperation), [prepared.row])


def _column_name_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def row_to_attr_values(model: type, row: dict[str, Any]) -> dict[str, Any]:
    name_to_key = _column_name_to_attr(model)
    return {
        attribute: value
        for name, value in row.items()
        if (attribute := name_to_key.get(name)) is not None
    }


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
    undoable: bool = True,
) -> dict[str, Any]:
    prepared = prepare_operation_write(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        payload=payload,
        inverse=inverse,
        now=now,
        undoable=undoable,
    )
    write_prepared_operation(db, prepared)
    return prepared.record


def operation_summary(operation: dict[str, Any]) -> OperationSummary:
    expires_at = operation.get("expiresAt")
    if not isinstance(expires_at, datetime):
        raise TypeError("Operation expiry is missing")
    return OperationSummary(
        id=str(operation["id"]),
        action=str(operation["action"]),
        status=str(operation["status"]),
        summary=str(operation["summary"]),
        expires_at=expires_at,
        undo_available=True,
    )


def get_operation(db: Session, operation_id: str) -> dict[str, Any] | None:
    operation = db.get(LibraryOperation, operation_id)
    return entity_record(operation) if operation is not None else None


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
    return [entity_record(row) for row in rows]


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
    values = row_to_attr_values(model, row)
    if not values:
        return
    mapper = sa_inspect(model)
    primary_key = list(mapper.primary_key)
    primary_key_attrs = {
        mapper.get_property_by_column(column).key for column in primary_key
    }
    statement = sqlite_insert(model).values(**values)
    update_set = {
        getattr(model, key): value
        for key, value in values.items()
        if key not in primary_key_attrs
    }
    if update_set:
        statement = statement.on_conflict_do_update(
            index_elements=primary_key,
            set_=update_set,
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=primary_key)
    db.execute(statement)


def restore_book_metadata(db: Session, row: dict[str, Any]) -> None:
    """Restore category-owned fields without touching directory topology identity."""

    book_id = str(row.get("id") or row.get("bookId") or "")
    if not book_id:
        raise ValueError("Book metadata snapshot is missing its id")
    field_map = {
        "author": "author",
        "normalizedAuthor": "normalized_author",
        "seriesName": "series_name",
        "seriesIndex": "series_index",
        "updatedAt": "updated_at",
    }
    values = {
        attribute: row[column]
        for column, attribute in field_map.items()
        if column in row
    }
    result = db.execute(
        update(LibraryBookMetadata)
        .where(LibraryBookMetadata.book_id == book_id)
        .values(**values)
    )
    if result.rowcount != 1:
        raise ValueError("Book metadata snapshot target does not exist")


def restore_resource_metadata(db: Session, row: dict[str, Any]) -> None:
    """Restore Resource metadata without touching source-tree identity."""

    resource_id = str(row.get("id") or row.get("resourceId") or "")
    if not resource_id:
        raise ValueError("Resource metadata snapshot is missing its id")
    field_map = {
        "publisher": "publisher",
        "language": "language",
        "publishedAt": "published_at",
        "identifier": "identifier",
        "isbn": "isbn",
        "pageCount": "page_count",
        "chapterCount": "chapter_count",
        "durationMs": "duration_ms",
        "trackCount": "track_count",
        "narrator": "narrator",
        "abridged": "abridged",
        "resourceIndex": "resource_index",
        "coverPath": "cover_path",
        "coverStatus": "cover_status",
        "updatedAt": "updated_at",
    }
    values = {
        attribute: row[column]
        for column, attribute in field_map.items()
        if column in row
    }
    result = db.execute(
        update(LibraryReadableResourceMetadata)
        .where(LibraryReadableResourceMetadata.resource_id == resource_id)
        .values(**values)
    )
    if result.rowcount != 1:
        raise ValueError("Resource metadata snapshot target does not exist")


def restore_facet_row(db: Session, facet_id: str, row: dict[str, Any]) -> None:
    del facet_id
    insert_snapshot(db, "LibraryFacet", row)


def delete_book_facets_for_book(db: Session, book_id: str) -> None:
    db.execute(delete(LibraryBookFacet).where(LibraryBookFacet.book_id == book_id))


def delete_resource_facets_for_resource(db: Session, resource_id: str) -> None:
    db.execute(
        delete(LibraryReadableResourceFacet).where(
            LibraryReadableResourceFacet.resource_id == resource_id
        )
    )

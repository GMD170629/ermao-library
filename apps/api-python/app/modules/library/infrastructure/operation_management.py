"""Restore canonical LibraryOperation snapshots through one transaction boundary."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import (
    LibraryBookFacet,
    LibraryFacet,
    LibraryOperation,
    LibraryReadableResource,
    LibraryReadableResourceFacet,
)
from app.modules.library.application.management_commands import (
    InvalidLibraryOperationError,
    LibraryOperationAuthorizationError,
    LibraryOperationManagementGateway,
    LibraryOperationNotFoundError,
)
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.books import entity_record

_FACET_ACTIONS = {"MERGE_FACETS", "RENAME_FACET", "DELETE_FACET"}
_BULK_METADATA_ACTIONS = {"BULK_UPDATE_METADATA", "BULK_FIND_REPLACE"}
_SUPPORTED_ACTIONS = {*_FACET_ACTIONS, *_BULK_METADATA_ACTIONS, "RECLASSIFY_RESOURCE"}


def _now() -> datetime:
    return datetime.now(UTC)


def _mapping_rows(inverse: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = inverse.get(key, [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise InvalidLibraryOperationError("撤销快照格式无效")
    return value


def _mapping(inverse: dict[str, Any], key: str) -> dict[str, Any]:
    value = inverse.get(key)
    if not isinstance(value, dict) or not value:
        raise InvalidLibraryOperationError("撤销快照不完整")
    return value


def _row_ids(rows: list[dict[str, Any]], key: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(row[key]) for row in rows if row.get(key) is not None)
    )


def _restore_books(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        operation_store.restore_book_metadata(db, row)


def _restore_resource_metadata(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        operation_store.restore_resource_metadata(db, row)


def _restore_facets(db: Session, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        operation_store.insert_snapshot(db, "LibraryFacet", row)


def _restore_links(
    db: Session,
    *,
    book_links: list[dict[str, Any]],
    resource_links: list[dict[str, Any]],
) -> None:
    for row in book_links:
        operation_store.insert_snapshot(db, "LibraryBookFacet", row)
    for row in resource_links:
        operation_store.insert_snapshot(db, "LibraryReadableResourceFacet", row)


def _restore_facet_operation(
    db: Session,
    *,
    action: str,
    inverse: dict[str, Any],
) -> None:
    books = _mapping_rows(inverse, "books")
    _restore_books(db, books)
    if action == "RENAME_FACET":
        operation_store.insert_snapshot(db, "LibraryFacet", _mapping(inverse, "facet"))
        return

    facets = (
        _mapping_rows(inverse, "facets")
        if action == "MERGE_FACETS"
        else [_mapping(inverse, "facet")]
    )
    book_links = _mapping_rows(inverse, "bookLinks")
    resource_links = _mapping_rows(inverse, "resourceLinks")
    _restore_facets(db, facets)
    if action == "MERGE_FACETS":
        facet_ids = _row_ids(facets, "id")
        book_ids = _row_ids(book_links, "bookId")
        resource_ids = _row_ids(resource_links, "resourceId")
        if facet_ids and book_ids:
            db.execute(
                delete(LibraryBookFacet).where(
                    LibraryBookFacet.facet_id.in_(facet_ids),
                    LibraryBookFacet.book_id.in_(book_ids),
                )
            )
        if facet_ids and resource_ids:
            db.execute(
                delete(LibraryReadableResourceFacet).where(
                    LibraryReadableResourceFacet.facet_id.in_(facet_ids),
                    LibraryReadableResourceFacet.resource_id.in_(resource_ids),
                )
            )
    _restore_links(
        db,
        book_links=book_links,
        resource_links=resource_links,
    )


def _delete_new_orphan_facets(db: Session, candidate_ids: set[str]) -> None:
    if not candidate_ids:
        return
    linked_ids = {
        str(facet_id)
        for facet_id in db.scalars(
            select(LibraryBookFacet.facet_id).where(
                LibraryBookFacet.facet_id.in_(candidate_ids)
            )
        ).all()
    }
    linked_ids.update(
        str(facet_id)
        for facet_id in db.scalars(
            select(LibraryReadableResourceFacet.facet_id).where(
                LibraryReadableResourceFacet.facet_id.in_(candidate_ids)
            )
        ).all()
    )
    orphan_ids = candidate_ids - linked_ids
    if orphan_ids:
        db.execute(delete(LibraryFacet).where(LibraryFacet.id.in_(orphan_ids)))


def _restore_bulk_metadata(db: Session, inverse: dict[str, Any]) -> None:
    books = _mapping_rows(inverse, "books")
    book_ids = _row_ids(books, "id")
    book_links = _mapping_rows(inverse, "bookLinks")
    facets = _mapping_rows(inverse, "facets")
    current_facet_ids = (
        {
            str(facet_id)
            for facet_id in db.scalars(
                select(LibraryBookFacet.facet_id).where(
                    LibraryBookFacet.book_id.in_(book_ids)
                )
            ).all()
        }
        if book_ids
        else set()
    )
    snapshot_facet_ids = set(_row_ids(facets, "id"))
    _restore_books(db, books)
    _restore_resource_metadata(db, _mapping_rows(inverse, "resources"))
    _restore_facets(db, facets)
    if book_ids:
        db.execute(
            delete(LibraryBookFacet).where(LibraryBookFacet.book_id.in_(book_ids))
        )
    _restore_links(db, book_links=book_links, resource_links=[])
    _delete_new_orphan_facets(db, current_facet_ids - snapshot_facet_ids)


def _restore_resource_classification(db: Session, inverse: dict[str, Any]) -> None:
    resources = _mapping_rows(inverse, "resources")
    if not resources:
        raise InvalidLibraryOperationError("撤销快照不完整")
    for row in resources:
        resource_id = str(row.get("id") or "")
        media_kind = str(row.get("mediaKind") or "")
        if not resource_id or not media_kind:
            raise InvalidLibraryOperationError("撤销快照不完整")
        result = db.execute(
            update(LibraryReadableResource)
            .where(LibraryReadableResource.id == resource_id)
            .values(
                media_kind=media_kind,
                **({"updated_at": row["updatedAt"]} if "updatedAt" in row else {}),
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise InvalidLibraryOperationError("撤销目标已不存在")


class SqlAlchemyLibraryOperationManagement(LibraryOperationManagementGateway):
    """Undo supported metadata operations without owning the transaction."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def undo_operation(
        self,
        operation_id: str,
        user_id: str,
        *,
        can_manage_system: bool,
    ) -> dict[str, object]:
        operation = self._db.get(LibraryOperation, operation_id)
        if operation is None:
            raise LibraryOperationNotFoundError
        if operation.user_id != user_id and not can_manage_system:
            raise LibraryOperationAuthorizationError
        if operation.status == "UNDONE":
            raise InvalidLibraryOperationError("该操作已经撤销")
        if operation.status != "COMPLETED":
            raise InvalidLibraryOperationError("该操作不可撤销")
        now = _now()
        expires_at = operation.expires_at
        if expires_at is None or expires_at < now:
            raise InvalidLibraryOperationError("撤销期限已过")
        action = operation.action
        if action not in _SUPPORTED_ACTIONS:
            raise InvalidLibraryOperationError("该操作不支持撤销")
        try:
            inverse = json.loads(operation.inverse_json)
        except (json.JSONDecodeError, TypeError):
            raise InvalidLibraryOperationError("撤销快照格式无效") from None
        if not isinstance(inverse, dict):
            raise InvalidLibraryOperationError("撤销快照格式无效")

        if action in _FACET_ACTIONS:
            _restore_facet_operation(self._db, action=action, inverse=inverse)
        elif action in _BULK_METADATA_ACTIONS:
            _restore_bulk_metadata(self._db, inverse)
        else:
            _restore_resource_classification(self._db, inverse)
        if not operation_store.mark_operation_undone(
            self._db,
            operation_id=operation.id,
            now=now,
        ):
            raise InvalidLibraryOperationError("该操作状态已改变")
        updated = entity_record(operation)
        updated.update({"status": "UNDONE", "undoneAt": now, "updatedAt": now})
        return {
            "operation": asdict(operation_store.operation_summary(updated)),
            "restored": True,
        }


__all__ = ["SqlAlchemyLibraryOperationManagement"]

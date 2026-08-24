"""Typed Book/ReadableResource joins used by library adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
)
from app.modules.library.infrastructure.books import entity_record


def get_resource_context(db: Session, resource_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadableResource, LibraryBook)
        .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
        .where(LibraryReadableResource.id == resource_id)
    ).first()
    if row is None:
        return None
    resource, book = row
    payload = entity_record(resource)
    payload.update(
        bookId=book.id,
        resourceId=resource.id,
    )
    return payload


def get_unit_context(db: Session, unit_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(
            ReadableResourceNavigationUnit,
            LibraryReadableResource,
            LibraryBook,
        )
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == ReadableResourceNavigationUnit.resource_id,
        )
        .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
        .where(ReadableResourceNavigationUnit.id == unit_id)
    ).first()
    if row is None:
        return None
    unit, resource, book = row
    payload = entity_record(unit)
    payload.update(
        bookId=book.id,
        resourceId=resource.id,
        format=resource.format,
    )
    return payload


def list_source_paths_for_book(db: Session, book_id: str) -> list[str]:
    paths = db.scalars(
        select(LibrarySourceNode.relative_path)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.source_node_id == LibrarySourceNode.id,
        )
        .where(LibraryReadableResource.book_id == book_id)
        .order_by(LibrarySourceNode.relative_path.asc())
    ).all()
    return [str(path) for path in paths]


def get_resource_for_book(
    db: Session, *, resource_id: str, book_id: str
) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadableResource, LibraryBook)
        .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
        .where(
            LibraryReadableResource.id == resource_id,
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.enablement_state == "ENABLED",
        )
    ).first()
    if row is None:
        return None
    resource, book = row
    payload = entity_record(resource)
    payload.update(
        sourceBookId=book.id,
        sourceFormat=resource.format,
        resourceId=resource.id,
    )
    return payload


def get_resource_belonging_to_book(
    db: Session, *, resource_id: str, book_id: str
) -> dict[str, Any] | None:
    return get_resource_for_book(db, resource_id=resource_id, book_id=book_id)


def list_asset_records_for_resource(
    db: Session, resource_id: str
) -> list[dict[str, Any]]:
    assets = db.scalars(
        select(LibraryResourceAsset)
        .where(
            LibraryResourceAsset.resource_id == resource_id,
            LibraryResourceAsset.import_state == "READY",
        )
        .order_by(
            LibraryResourceAsset.sequence_index.asc(),
            LibraryResourceAsset.id.asc(),
        )
    ).all()
    return [entity_record(asset) for asset in assets]


__all__ = [
    "get_resource_belonging_to_book",
    "get_resource_context",
    "get_resource_for_book",
    "get_unit_context",
    "list_asset_records_for_resource",
    "list_source_paths_for_book",
]

"""Book persistence projections for the Library capability."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import LibraryBook, LibraryBookMetadata

STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}


def entity_record(entity: object) -> dict[str, Any]:
    """Return an ORM row as a transport-neutral column record."""

    mapper = sa_inspect(entity, raiseerr=True).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def _book_record(
    book: LibraryBook,
    metadata: LibraryBookMetadata | None,
) -> dict[str, Any]:
    return {
        "id": book.id,
        "libraryId": book.library_id,
        "sourceNodeId": book.source_node_id,
        "visibilityState": book.visibility_state,
        "curationState": book.curation_state,
        "createdAt": book.created_at,
        "updatedAt": book.updated_at,
        "title": metadata.title if metadata else "",
        "author": metadata.author if metadata else None,
        "description": metadata.description if metadata else None,
        "seriesName": metadata.series_name if metadata else None,
        "seriesIndex": metadata.series_index if metadata else None,
        "coverPath": metadata.cover_path if metadata else None,
        "coverStatus": metadata.cover_status if metadata else "PENDING",
        "metadataQuality": metadata.metadata_quality if metadata else 0,
        "publicationStatus": metadata.publication_status if metadata else "UNKNOWN",
        "trackingStatus": metadata.tracking_status if metadata else "NOT_TRACKING",
    }


def _book_statement(book_ids: str | Collection[str] | None = None):
    statement = select(LibraryBook, LibraryBookMetadata).outerjoin(
        LibraryBookMetadata,
        LibraryBookMetadata.book_id == LibraryBook.id,
    )
    if isinstance(book_ids, str):
        statement = statement.where(LibraryBook.id == book_ids)
    elif book_ids is not None:
        statement = statement.where(LibraryBook.id.in_(book_ids))
    return statement


def get_visible_book(db: Session, book_id: str) -> dict[str, Any] | None:
    row = db.execute(
        _book_statement(book_id).where(LibraryBook.visibility_state == "VISIBLE")
    ).first()
    return _book_record(row[0], row[1]) if row is not None else None


def get_book(db: Session, book_id: str) -> dict[str, Any] | None:
    row = db.execute(_book_statement(book_id)).first()
    return _book_record(row[0], row[1]) if row is not None else None


def list_books_by_ids(
    db: Session,
    book_ids: tuple[str, ...] | list[str],
) -> list[dict[str, Any]]:
    if not book_ids:
        return []
    rows = db.execute(_book_statement(book_ids)).all()
    by_id = {str(row[0].id): _book_record(row[0], row[1]) for row in rows}
    return [by_id[book_id] for book_id in book_ids if book_id in by_id]


def _metadata_values(values: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "seriesName": "series_name",
        "seriesIndex": "series_index",
        "coverPath": "cover_path",
        "coverStatus": "cover_status",
        "metadataQuality": "metadata_quality",
        "publicationStatus": "publication_status",
        "trackingStatus": "tracking_status",
    }
    allowed = {
        "title",
        "author",
        "description",
        "series_name",
        "series_index",
        "cover_path",
        "cover_status",
        "metadata_quality",
        "publication_status",
        "tracking_status",
    }
    return {
        aliases.get(key, key): value
        for key, value in values.items()
        if aliases.get(key, key) in allowed
    }


def update_book_fields(
    db: Session,
    book_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    book_values = {
        "visibility_state": values.get(
            "visibility_state", values.get("visibilityState")
        ),
        "curation_state": values.get("curation_state", values.get("curationState")),
    }
    book_values = {
        key: value for key, value in book_values.items() if value is not None
    }
    if book_values:
        db.execute(
            update(LibraryBook).where(LibraryBook.id == book_id).values(**book_values)
        )
    metadata_values = _metadata_values(values)
    if metadata_values:
        metadata = db.get(LibraryBookMetadata, book_id)
        if metadata is None:
            title = str(metadata_values.get("title", ""))
            metadata = LibraryBookMetadata(
                book_id=book_id,
                title=title,
                normalized_title=title.casefold(),
            )
            db.add(metadata)
        for key, value in metadata_values.items():
            setattr(metadata, key, value)
    return get_book(db, book_id)


def update_book_fields_bulk(
    db: Session,
    updates: tuple[tuple[str, dict[str, Any]], ...],
) -> int:
    changed = 0
    for book_id, values in updates:
        if update_book_fields(db, book_id, values) is not None:
            changed += 1
    return changed


__all__ = [
    "STATUS_RANK",
    "entity_record",
    "get_book",
    "get_visible_book",
    "list_books_by_ids",
    "update_book_fields",
    "update_book_fields_bulk",
]

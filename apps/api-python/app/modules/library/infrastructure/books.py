"""Book persistence projections for the Library capability."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import LibraryBook, LibraryBookMetadata, LibraryReadableResource
from app.modules.library.domain.facets import normalize_facet_name
from app.modules.library.infrastructure.book_covers import SqlAlchemyBookCoverQueries

STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}


@dataclass(frozen=True, slots=True)
class ResourceImportSummary:
    ready: int = 0
    pending: int = 0
    failed: int = 0

    def as_record(self) -> dict[str, int]:
        return {
            "ready": self.ready,
            "pending": self.pending,
            "failed": self.failed,
        }


def resource_import_summaries(
    db: Session,
    book_ids: Collection[str],
) -> dict[str, ResourceImportSummary]:
    """Count enabled resources for an already-authorized page of Books."""

    normalized_ids = tuple(dict.fromkeys(str(book_id) for book_id in book_ids))
    if not normalized_ids:
        return {}
    counts: dict[str, dict[str, int]] = {
        book_id: {"READY": 0, "PENDING": 0, "FAILED": 0} for book_id in normalized_ids
    }
    rows = db.execute(
        select(
            LibraryReadableResource.book_id,
            LibraryReadableResource.import_state,
            func.count().label("resource_count"),
        )
        .where(
            LibraryReadableResource.book_id.in_(normalized_ids),
            LibraryReadableResource.enablement_state == "ENABLED",
        )
        .group_by(
            LibraryReadableResource.book_id,
            LibraryReadableResource.import_state,
        )
    ).all()
    for row in rows:
        state = str(row.import_state)
        if state in counts[str(row.book_id)]:
            counts[str(row.book_id)][state] = int(row.resource_count or 0)
    return {
        book_id: ResourceImportSummary(
            ready=state_counts["READY"],
            pending=state_counts["PENDING"],
            failed=state_counts["FAILED"],
        )
        for book_id, state_counts in counts.items()
    }


def entity_record(entity: object) -> dict[str, Any]:
    """Return an ORM row as a transport-neutral column record."""

    mapper = sa_inspect(entity, raiseerr=True).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def _book_record(
    book: LibraryBook,
    metadata: LibraryBookMetadata | None,
    effective_cover_path: str | None = None,
    resource_import_summary: ResourceImportSummary | None = None,
) -> dict[str, Any]:
    cover_path = effective_cover_path or (metadata.cover_path if metadata else None)
    import_summary = resource_import_summary or ResourceImportSummary()
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
        "coverPath": cover_path,
        "coverStatus": "READY"
        if effective_cover_path
        else (metadata.cover_status if metadata else "PENDING"),
        "metadataQuality": metadata.metadata_quality if metadata else 0,
        "publicationStatus": metadata.publication_status if metadata else "UNKNOWN",
        "trackingStatus": metadata.tracking_status if metadata else "NOT_TRACKING",
        "resourceImportSummary": import_summary.as_record(),
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
    if row is None:
        return None
    cover_path = SqlAlchemyBookCoverQueries(db).preferred_paths((book_id,)).get(book_id)
    import_summary = resource_import_summaries(db, (book_id,))[book_id]
    return _book_record(row[0], row[1], cover_path, import_summary)


def get_book(db: Session, book_id: str) -> dict[str, Any] | None:
    row = db.execute(_book_statement(book_id)).first()
    if row is None:
        return None
    cover_path = SqlAlchemyBookCoverQueries(db).preferred_paths((book_id,)).get(book_id)
    import_summary = resource_import_summaries(db, (book_id,))[book_id]
    return _book_record(row[0], row[1], cover_path, import_summary)


def list_books_by_ids(
    db: Session,
    book_ids: tuple[str, ...] | list[str],
) -> list[dict[str, Any]]:
    if not book_ids:
        return []
    rows = db.execute(_book_statement(book_ids)).all()
    cover_paths = SqlAlchemyBookCoverQueries(db).preferred_paths(tuple(book_ids))
    import_summaries = resource_import_summaries(db, book_ids)
    by_id = {
        str(row[0].id): _book_record(
            row[0],
            row[1],
            cover_paths.get(str(row[0].id)),
            import_summaries[str(row[0].id)],
        )
        for row in rows
    }
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
        "normalized_author",
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
    if "author" in metadata_values:
        author = metadata_values["author"]
        metadata_values["normalized_author"] = (
            normalize_facet_name(str(author)) if author is not None else None
        )
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
    "resource_import_summaries",
    "update_book_fields",
    "update_book_fields_bulk",
]

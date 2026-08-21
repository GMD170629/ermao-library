"""ORM persistence for organize review jobs and book/resource context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.organize import OrganizeJob
from app.modules.organize.infrastructure.eligibility import book_entity_record
from app.modules.organize.infrastructure.runs import job_entity_record

JOB_UPDATE_FIELD_MAP = {
    "status": "status",
    "issueCodes": "issue_codes",
    "reasonCodes": "reason_codes",
    "summary": "summary",
    "errorSummary": "error_summary",
    "updatedAt": "updated_at",
    "startedAt": "started_at",
    "finishedAt": "finished_at",
    "trigger": "trigger",
    "resourceId": "resource_id",
}
BOOK_UPDATE_FIELD_MAP = {
    "visibilityState": "visibility_state",
    "curationState": "curation_state",
    "updatedAt": "updated_at",
}


def resource_entity_as_dict(entity: LibraryReadableResource) -> dict[str, Any]:
    return {
        "id": entity.id,
        "bookId": entity.book_id,
        "sourceNodeId": entity.source_node_id,
        "format": entity.format,
        "mediaKind": entity.media_kind,
        "enablementState": entity.enablement_state,
        "importState": entity.import_state,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def get_job(db: Session, job_id: str) -> dict[str, Any] | None:
    entity = db.get(OrganizeJob, job_id)
    return job_entity_record(entity) if entity is not None else None


def get_book(db: Session, book_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryBook, LibraryBookMetadata)
        .outerjoin(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(LibraryBook.id == book_id)
    ).first()
    return book_entity_record(row[0], row[1]) if row is not None else None


def _resources_for_book(
    db: Session, book_id: str, *, visible_only: bool
) -> list[LibraryReadableResource]:
    query = select(LibraryReadableResource).where(
        LibraryReadableResource.book_id == book_id
    )
    if visible_only:
        query = query.where(LibraryReadableResource.enablement_state == "ENABLED")
    return list(
        db.scalars(
            query.order_by(
                LibraryReadableResource.created_at.asc(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
    )


def earliest_resource_id(db: Session, book_id: str) -> str | None:
    resources = _resources_for_book(db, book_id, visible_only=True)
    return resources[0].id if resources else None


def update_job(
    db: Session, job_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    mapped: dict[str, Any] = {}
    field_map = {
        "status": "status",
        "issueCodes": "issue_codes",
        "reasonCodes": "reason_codes",
        "summary": "summary",
        "errorSummary": "error_summary",
        "updatedAt": "updated_at",
        "startedAt": "started_at",
        "finishedAt": "finished_at",
        "trigger": "trigger",
        "resourceId": "resource_id",
    }
    for key, value in values.items():
        attr = field_map.get(key)
        if attr is not None:
            mapped[attr] = value
    if mapped:
        db.execute(update(OrganizeJob).where(OrganizeJob.id == job_id).values(**mapped))
    return get_job(db, job_id)


def prepare_job_update_rows(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": row["id"],
            **{
                mapped_key: value
                for key, value in row.items()
                if (mapped_key := JOB_UPDATE_FIELD_MAP.get(key)) is not None
            },
        }
        for row in rows
    )


def write_prepared_job_updates(db: Session, rows: tuple[dict[str, Any], ...]) -> None:
    if rows:
        db.execute(update(OrganizeJob), list(rows))


def update_book(
    db: Session, book_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    book_values = {
        key: values[key]
        for key in ("visibilityState", "curationState", "updatedAt")
        if key in values
    }
    if book_values:
        db.execute(
            update(LibraryBook)
            .where(LibraryBook.id == book_id)
            .values(
                **{
                    mapped_key: value
                    for key, value in book_values.items()
                    if (mapped_key := BOOK_UPDATE_FIELD_MAP.get(key)) is not None
                }
            )
        )
    metadata_map = {
        "title": "title",
        "normalizedTitle": "normalized_title",
        "author": "author",
        "normalizedAuthor": "normalized_author",
        "description": "description",
        "seriesName": "series_name",
        "seriesIndex": "series_index",
        "coverPath": "cover_path",
        "coverStatus": "cover_status",
        "metadataQuality": "metadata_quality",
        "publicationStatus": "publication_status",
        "trackingStatus": "tracking_status",
        "updatedAt": "updated_at",
    }
    metadata_values = {
        mapped_key: values[key]
        for key, mapped_key in metadata_map.items()
        if key in values
    }
    if metadata_values:
        metadata = db.get(LibraryBookMetadata, book_id)
        if metadata is None:
            metadata = LibraryBookMetadata(
                book_id=book_id,
                title=str(metadata_values.get("title") or ""),
                normalized_title=str(
                    metadata_values.get("normalized_title")
                    or metadata_values.get("title")
                    or ""
                ).casefold(),
            )
            db.add(metadata)
        for key, value in metadata_values.items():
            setattr(metadata, key, value)
    return get_book(db, book_id)


def prepare_book_update_rows(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": row["id"],
            **{
                mapped_key: value
                for key, value in row.items()
                if (mapped_key := BOOK_UPDATE_FIELD_MAP.get(key)) is not None
            },
        }
        for row in rows
    )


def write_prepared_book_updates(db: Session, rows: tuple[dict[str, Any], ...]) -> None:
    if rows:
        db.execute(update(LibraryBook), list(rows))


def list_files_for_resource(db: Session, resource_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryResourceAsset,
            LibrarySourceNode,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .where(LibraryResourceAsset.resource_id == resource_id)
        .order_by(
            LibraryResourceAsset.sequence_index.asc().nulls_last(),
            LibraryResourceAsset.id.asc(),
        )
    ).all()
    return [
        {
            "id": asset.id,
            "resourceId": asset.resource_id,
            "sourceNodeId": asset.source_node_id,
            "relativePath": source_node.relative_path,
            "name": source_node.name,
            "role": asset.role,
            "importState": asset.import_state,
            "sequenceIndex": asset.sequence_index,
            "sortKey": asset.sort_key,
            "failureReason": asset.failure_reason,
            "createdAt": asset.created_at,
            "updatedAt": asset.updated_at,
        }
        for asset, source_node in rows
    ]


def list_metadata_for_book(db: Session, book_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LibraryBookMetadata).where(LibraryBookMetadata.book_id == book_id)
    ).all()
    return [
        {
            "bookId": row.book_id,
            "title": row.title,
            "normalizedTitle": row.normalized_title,
            "author": row.author,
            "normalizedAuthor": row.normalized_author,
            "description": row.description,
            "seriesName": row.series_name,
            "seriesIndex": row.series_index,
            "coverPath": row.cover_path,
            "coverStatus": row.cover_status,
            "metadataQuality": row.metadata_quality,
            "publicationStatus": row.publication_status,
            "trackingStatus": row.tracking_status,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def load_book_context(db: Session, book_id: str) -> dict[str, Any] | None:
    book = get_book(db, book_id)
    if not book:
        return None
    resources = list_resources_for_book(db, str(book["id"]))
    files: list[dict[str, Any]] = []
    for resource in resources:
        files.extend(list_files_for_resource(db, str(resource["id"])))
    metadata = list_metadata_for_book(db, book_id)
    return {"book": book, "resources": resources, "files": files, "metadata": metadata}


def list_resources_for_book(db: Session, book_id: str) -> list[dict[str, Any]]:
    return [
        resource_entity_as_dict(row)
        for row in _resources_for_book(db, book_id, visible_only=False)
    ]

"""ORM persistence for organize review job / work / context reads and updates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models import (
    LibraryResourceAsset,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryBook,
)
from app.models.organize import OrganizeJob
from app.modules.library.domain.resource_identity import IMPLICIT_RESOURCE_SOURCE_KEY
from app.modules.organize.infrastructure.eligibility import work_entity_record
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
WORK_UPDATE_FIELD_MAP = {
    "title": "title",
    "author": "author",
    "normalizedTitle": "normalized_title",
    "normalizedAuthor": "normalized_author",
    "description": "description",
    "tags": "tags",
    "seriesName": "series_name",
    "seriesIndex": "series_index",
    "organized": "organized",
    "organizeStatus": "organize_status",
    "metadataQuality": "metadata_quality",
    "hidden": "hidden",
    "coverPath": "cover_path",
    "coverStatus": "cover_status",
    "updatedAt": "updated_at",
}


def volume_entity_as_dict(entity: LibraryReadableResource) -> dict[str, Any]:
    return {
        "id": entity.id,
        "resourceId": entity.resource_id,
        "title": entity.title,
        "volumeIndex": entity.volume_index,
        "sortOrder": entity.sort_order,
        "format": entity.format,
        "classificationSource": entity.classification_source,
        "suggestedMediaKind": entity.suggested_media_kind,
        "resourceKey": entity.resource_key,
        "importStatus": entity.import_status,
        "importError": entity.import_error,
        "isbn": entity.isbn,
        "identifier": entity.identifier,
        "hidden": entity.hidden,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


def has_table(db: Session, table: str) -> bool:
    return _has_table(db, table)


def get_job(db: Session, job_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "OrganizeJob"):
        return None
    entity = db.get(OrganizeJob, job_id)
    return job_entity_record(entity) if entity is not None else None


def get_work(db: Session, book_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryBook"):
        return None
    entity = db.get(LibraryBook, book_id)
    return work_entity_record(entity) if entity is not None else None


def _volumes_belonging_to_work(
    db: Session, book_id: str, *, visible_only: bool
) -> list[LibraryReadableResource]:
    if not _has_table(db, "LibraryReadableResource") or not _has_table(db, "LibraryReadableResource"):
        return []
    query = (
        select(LibraryReadableResource)
        .join(LibraryReadableResource, LibraryReadableResource.id == LibraryReadableResource.resource_id)
        .where(LibraryReadableResource.book_id == book_id)
    )
    if visible_only:
        query = query.where(LibraryReadableResource.hidden.is_(False))
    return list(
        db.scalars(
            query.order_by(
                case(
                    (LibraryReadableResource.source_key == IMPLICIT_RESOURCE_SOURCE_KEY, 0),
                    else_=1,
                ),
                func.coalesce(LibraryReadableResource.source_name, ""),
                LibraryReadableResource.source_key.asc(),
                LibraryReadableResource.id.asc(),
                LibraryReadableResource.sort_order.asc(),
                LibraryReadableResource.created_at.asc(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
    )


def earliest_resource_id(db: Session, book_id: str) -> str | None:
    volumes = _volumes_belonging_to_work(db, book_id, visible_only=True)
    return volumes[0].id if volumes else None


def update_job(
    db: Session, job_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    if not _has_table(db, "OrganizeJob"):
        return None
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
    if not _has_table(db, "LibraryBook"):
        return None
    field_map = {
        "title": "title",
        "author": "author",
        "normalizedTitle": "normalized_title",
        "normalizedAuthor": "normalized_author",
        "description": "description",
        "tags": "tags",
        "seriesName": "series_name",
        "seriesIndex": "series_index",
        "organized": "organized",
        "organizeStatus": "organize_status",
        "metadataQuality": "metadata_quality",
        "hidden": "hidden",
        "coverPath": "cover_path",
        "coverStatus": "cover_status",
        "updatedAt": "updated_at",
    }
    mapped: dict[str, Any] = {}
    for key, value in values.items():
        attr = field_map.get(key)
        if attr is not None:
            mapped[attr] = value
    if mapped:
        db.execute(
            update(LibraryBook).where(LibraryBook.id == book_id).values(**mapped)
        )
    return get_work(db, book_id)


def prepare_work_update_rows(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": row["id"],
            **{
                mapped_key: value
                for key, value in row.items()
                if (mapped_key := WORK_UPDATE_FIELD_MAP.get(key)) is not None
            },
        }
        for row in rows
    )


def write_prepared_work_updates(db: Session, rows: tuple[dict[str, Any], ...]) -> None:
    if rows:
        db.execute(update(LibraryBook), list(rows))


def list_files_for_volume(db: Session, resource_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryResourceAsset"):
        return []
    # Project only columns shared by production schema and lean test fixtures.
    rows = db.execute(
        select(
            LibraryResourceAsset.id,
            LibraryResourceAsset.resource_id,
            LibraryResourceAsset.path,
            LibraryResourceAsset.file_path_hash,
            LibraryResourceAsset.mtime_ms,
            LibraryResourceAsset.kind,
            LibraryResourceAsset.mime_type,
            LibraryResourceAsset.size_bytes,
            LibraryResourceAsset.sort_order,
            LibraryResourceAsset.created_at,
            LibraryResourceAsset.updated_at,
        ).where(LibraryResourceAsset.resource_id == resource_id)
    ).all()
    return [
        {
            "id": row.id,
            "resourceId": row.resource_id,
            "path": row.path,
            "filePathHash": row.file_path_hash,
            "mtimeMs": row.mtime_ms,
            "kind": row.kind,
            "mimeType": row.mime_type,
            "sizeBytes": row.size_bytes,
            "sortOrder": row.sort_order,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def list_metadata_for_volume(db: Session, resource_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryBookMetadata"):
        return []
    rows = db.scalars(
        select(LibraryBookMetadata).where(LibraryBookMetadata.book_id == resource_id)
    ).all()
    return [
        {
            "id": row.id,
            "resourceId": row.resource_id,
            "source": row.source,
            "rawJson": row.raw_json,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def load_work_context(db: Session, book_id: str) -> dict[str, Any] | None:
    work = get_work(db, book_id)
    if not work:
        return None
    volumes = list_volumes_for_work(db, str(work["id"]))
    files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for volume in volumes:
        files.extend(list_files_for_volume(db, str(volume["id"])))
        metadata.extend(list_metadata_for_volume(db, str(volume["id"])))
    return {"work": work, "volumes": volumes, "files": files, "metadata": metadata}


def list_volumes_for_work(db: Session, book_id: str) -> list[dict[str, Any]]:
    return [
        volume_entity_as_dict(row)
        for row in _volumes_belonging_to_work(db, book_id, visible_only=False)
    ]


def work_column_names(db: Session) -> set[str]:
    if not _has_table(db, "LibraryBook"):
        return set()
    return {
        column["name"] for column in inspect(db.connection()).get_columns("LibraryBook")
    }

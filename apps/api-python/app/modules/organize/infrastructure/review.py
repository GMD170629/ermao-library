"""ORM persistence for organize review job / work / context reads and updates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.library import LibraryEdition, LibraryFile, LibraryMetadata, LibraryWork
from app.models.organize import OrganizeJob
from app.modules.organize.infrastructure.duplicates import list_editions_for_work
from app.modules.organize.infrastructure.eligibility import UNRESOLVED_JOB_STATUSES, work_entity_as_legacy_dict
from app.modules.organize.infrastructure.runs import job_entity_as_legacy_dict


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


def has_table(db: Session, table: str) -> bool:
    return _has_table(db, table)


def get_job(db: Session, job_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "OrganizeJob"):
        return None
    entity = db.get(OrganizeJob, job_id)
    return job_entity_as_legacy_dict(entity) if entity is not None else None


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryWork"):
        return None
    entity = db.get(LibraryWork, work_id)
    return work_entity_as_legacy_dict(entity) if entity is not None else None


def get_visible_work(db: Session, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryWork"):
        return None
    entity = db.scalar(
        select(LibraryWork).where(
            LibraryWork.id == work_id,
            func.coalesce(LibraryWork.hidden, False).is_(False),
        )
    )
    return work_entity_as_legacy_dict(entity) if entity is not None else None


def get_unresolved_job_for_work(db: Session, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "OrganizeJob"):
        return None
    entity = db.scalars(
        select(OrganizeJob)
        .where(
            OrganizeJob.work_id == work_id,
            OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
        )
        .order_by(OrganizeJob.updated_at.desc())
        .limit(1)
    ).first()
    return job_entity_as_legacy_dict(entity) if entity is not None else None


def earliest_edition_id(db: Session, work_id: str) -> str | None:
    if not _has_table(db, "LibraryEdition"):
        return None
    return db.scalar(
        select(LibraryEdition.id)
        .where(LibraryEdition.work_id == work_id)
        .order_by(LibraryEdition.created_at.asc())
        .limit(1)
    )


def insert_organize_job(
    db: Session,
    *,
    job_id: str,
    work_id: str,
    edition_id: str | None,
    status: str,
    issue_codes_json: str,
    summary: str,
    now: Any,
) -> dict[str, Any]:
    entity = OrganizeJob(
        id=job_id,
        work_id=work_id,
        edition_id=edition_id,
        trigger="LEGACY",
        status=status,
        issue_codes=issue_codes_json,
        reason_codes="[]",
        summary=summary,
        created_at=now,
        updated_at=now,
    )
    db.add(entity)
    db.flush()
    return job_entity_as_legacy_dict(entity)


def update_job(db: Session, job_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
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
        "editionId": "edition_id",
    }
    for key, value in values.items():
        attr = field_map.get(key)
        if attr is not None:
            mapped[attr] = value
    if mapped:
        db.execute(update(OrganizeJob).where(OrganizeJob.id == job_id).values(**mapped))
        db.flush()
    return get_job(db, job_id)


def update_work(db: Session, work_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryWork"):
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
        "publishedYear": "published_year",
        "mergeKey": "merge_key",
        "organized": "organized",
        "organizeStatus": "organize_status",
        "metadataQuality": "metadata_quality",
        "hidden": "hidden",
        "primaryEditionId": "primary_edition_id",
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
        db.execute(update(LibraryWork).where(LibraryWork.id == work_id).values(**mapped))
        db.flush()
    return get_work(db, work_id)


def list_files_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryFile"):
        return []
    # Project only columns shared by production schema and lean test fixtures.
    rows = db.execute(
        select(
            LibraryFile.id,
            LibraryFile.edition_id,
            LibraryFile.volume_id,
            LibraryFile.path,
            LibraryFile.file_path_hash,
            LibraryFile.fingerprint,
            LibraryFile.full_hash,
            LibraryFile.hash_status,
            LibraryFile.mtime_ms,
            LibraryFile.kind,
            LibraryFile.mime_type,
            LibraryFile.size_bytes,
            LibraryFile.sort_order,
            LibraryFile.created_at,
            LibraryFile.updated_at,
        ).where(LibraryFile.edition_id == edition_id)
    ).all()
    return [
        {
            "id": row.id,
            "editionId": row.edition_id,
            "volumeId": row.volume_id,
            "path": row.path,
            "filePathHash": row.file_path_hash,
            "fingerprint": row.fingerprint,
            "fullHash": row.full_hash,
            "hashStatus": row.hash_status,
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


def list_metadata_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryMetadata"):
        return []
    rows = db.scalars(select(LibraryMetadata).where(LibraryMetadata.edition_id == edition_id)).all()
    return [
        {
            "id": row.id,
            "editionId": row.edition_id,
            "source": row.source,
            "rawJson": row.raw_json,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def load_job_context(db: Session, job: dict[str, Any]) -> dict[str, Any] | None:
    work_id = job.get("workId")
    if not work_id:
        return None
    work = get_work(db, str(work_id))
    if not work:
        return None
    editions = list_editions_for_work(db, str(work["id"]))
    files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for edition in editions:
        files.extend(list_files_for_edition(db, str(edition["id"])))
        metadata.extend(list_metadata_for_edition(db, str(edition["id"])))
    return {"work": work, "editions": editions, "files": files, "metadata": metadata}


def work_column_names(db: Session) -> set[str]:
    if not _has_table(db, "LibraryWork"):
        return set()
    return {column["name"] for column in inspect(db.connection()).get_columns("LibraryWork")}

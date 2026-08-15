"""ORM persistence for organize review job / work / context reads and updates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, insert, inspect, select, update
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import OrganizeJob
from app.modules.organize.infrastructure.duplicates import volume_entity_as_dict
from app.modules.organize.infrastructure.eligibility import (
    UNRESOLVED_JOB_STATUSES,
    work_entity_as_legacy_dict,
)
from app.modules.organize.infrastructure.runs import job_entity_as_legacy_dict

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
    "volumeId": "volume_id",
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
    "mergeKey": "merge_key",
    "organized": "organized",
    "organizeStatus": "organize_status",
    "metadataQuality": "metadata_quality",
    "hidden": "hidden",
    "coverPath": "cover_path",
    "coverStatus": "cover_status",
    "updatedAt": "updated_at",
}


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


def earliest_volume_id(db: Session, work_id: str) -> str | None:
    if not _has_table(db, "LibraryVolume"):
        return None
    return db.scalar(
        select(LibraryVolume.id)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
        )
        .order_by(
            case(
                (LibraryMediaVersion.media_kind == "EBOOK", 0),
                (LibraryMediaVersion.media_kind == "COMIC", 1),
                (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(1)
    )


def insert_organize_job(
    db: Session,
    *,
    job_id: str,
    work_id: str,
    volume_id: str | None,
    status: str,
    issue_codes_json: str,
    summary: str,
    now: Any,
) -> dict[str, Any]:
    db.execute(
        insert(OrganizeJob).values(
            id=job_id,
            work_id=work_id,
            volume_id=volume_id,
            trigger="LEGACY",
            status=status,
            issue_codes=issue_codes_json,
            reason_codes="[]",
            summary=summary,
            created_at=now,
            updated_at=now,
        )
    )
    return {
        "id": job_id,
        "runId": None,
        "workId": work_id,
        "volumeId": volume_id,
        "mediaVersionId": None,
        "importTaskId": None,
        "trigger": "LEGACY",
        "status": status,
        "issueCodes": issue_codes_json,
        "reasonCodes": "[]",
        "summary": summary,
        "errorSummary": None,
        "startedAt": None,
        "finishedAt": None,
        "createdAt": now,
        "updatedAt": now,
    }


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
        "volumeId": "volume_id",
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


def write_prepared_job_updates(
    db: Session, rows: tuple[dict[str, Any], ...]
) -> None:
    if rows:
        db.execute(update(OrganizeJob), list(rows))


def update_work(
    db: Session, work_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
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
        "mergeKey": "merge_key",
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
            update(LibraryWork).where(LibraryWork.id == work_id).values(**mapped)
        )
    return get_work(db, work_id)


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


def write_prepared_work_updates(
    db: Session, rows: tuple[dict[str, Any], ...]
) -> None:
    if rows:
        db.execute(update(LibraryWork), list(rows))


def list_files_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryFile"):
        return []
    # Project only columns shared by production schema and lean test fixtures.
    rows = db.execute(
        select(
            LibraryFile.id,
            LibraryFile.volume_id,
            LibraryFile.path,
            LibraryFile.file_path_hash,
            LibraryFile.mtime_ms,
            LibraryFile.kind,
            LibraryFile.mime_type,
            LibraryFile.size_bytes,
            LibraryFile.sort_order,
            LibraryFile.created_at,
            LibraryFile.updated_at,
        ).where(LibraryFile.volume_id == volume_id)
    ).all()
    return [
        {
            "id": row.id,
            "volumeId": row.volume_id,
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


def list_metadata_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryMetadata"):
        return []
    rows = db.scalars(
        select(LibraryMetadata).where(LibraryMetadata.volume_id == volume_id)
    ).all()
    return [
        {
            "id": row.id,
            "volumeId": row.volume_id,
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
    volumes = list_volumes_for_work(db, str(work["id"]))
    files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for volume in volumes:
        files.extend(list_files_for_volume(db, str(volume["id"])))
        metadata.extend(list_metadata_for_volume(db, str(volume["id"])))
    return {"work": work, "volumes": volumes, "files": files, "metadata": metadata}


def list_volumes_for_work(db: Session, work_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryVolume"):
        return []
    rows = db.scalars(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryMediaVersion.work_id == work_id)
        .order_by(
            case(
                (LibraryMediaVersion.media_kind == "EBOOK", 0),
                (LibraryMediaVersion.media_kind == "COMIC", 1),
                (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    return [volume_entity_as_dict(row) for row in rows]


def work_column_names(db: Session) -> set[str]:
    if not _has_table(db, "LibraryWork"):
        return set()
    return {
        column["name"] for column in inspect(db.connection()).get_columns("LibraryWork")
    }

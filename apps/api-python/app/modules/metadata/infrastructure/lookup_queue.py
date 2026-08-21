"""ORM persistence helpers for metadata lookup queue tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
)
from app.models.organize import (
    MetadataLookupTask,
    MetadataProviderExecution,
    OrganizeJob,
    OrganizePolicy,
)

STALE_RUNNING_MINUTES = 10
LOOKUP_LEASE_SECONDS = 60

_LOOKUP_TASK_CAMEL_TO_SNAKE: dict[str, str] = {
    "status": "status",
    "attempts": "attempts",
    "nextAttemptAt": "next_attempt_at",
    "resultSource": "result_source",
    "candidateRawJson": "candidate_raw_json",
    "appliedFields": "applied_fields",
    "errorSummary": "error_summary",
    "startedAt": "started_at",
    "finishedAt": "finished_at",
    "updatedAt": "updated_at",
    "providerOrder": "provider_order",
    "leaseOwnerId": "lease_owner_id",
    "leaseExpiresAt": "lease_expires_at",
}

_BOOK_METADATA_CAMEL_TO_SNAKE: dict[str, str] = {
    "title": "title",
    "author": "author",
    "description": "description",
    "seriesName": "series_name",
    "seriesIndex": "series_index",
    "coverPath": "cover_path",
    "coverStatus": "cover_status",
    "normalizedTitle": "normalized_title",
    "normalizedAuthor": "normalized_author",
    "metadataQuality": "metadata_quality",
    "updatedAt": "updated_at",
}

_RESOURCE_METADATA_CAMEL_TO_SNAKE: dict[str, str] = {
    "publisher": "publisher",
    "publishedAt": "published_at",
    "language": "language",
    "isbn": "isbn",
    "updatedAt": "updated_at",
}


@dataclass(frozen=True, slots=True)
class PreparedProviderExecutionWrite:
    statement: Executable | None
    execution_id: str | None


def lookup_task_to_dict(task: MetadataLookupTask) -> dict[str, Any]:
    """Map ORM task attrs to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": task.id,
        "bookId": task.book_id,
        "resourceId": task.resource_id,
        "importTaskId": task.import_task_id,
        "organizeJobId": task.organize_job_id,
        "status": task.status,
        "providerOrder": task.provider_order,
        "attempts": task.attempts,
        "nextAttemptAt": task.next_attempt_at,
        "leaseOwnerId": task.lease_owner_id,
        "leaseExpiresAt": task.lease_expires_at,
        "resultSource": task.result_source,
        "candidateRawJson": task.candidate_raw_json,
        "appliedFields": task.applied_fields,
        "errorSummary": task.error_summary,
        "startedAt": task.started_at,
        "finishedAt": task.finished_at,
        "createdAt": task.created_at,
        "updatedAt": task.updated_at,
    }


def automatic_rate_limit_applies(db: Session, task: dict[str, Any]) -> bool:
    """Manual recognition is explicit; every background trigger stays safe."""

    job_id = str(task.get("organizeJobId") or "").strip()
    if not job_id:
        return True
    trigger = db.scalar(select(OrganizeJob.trigger).where(OrganizeJob.id == job_id))
    return str(trigger or "SCHEDULE").upper() != "MANUAL"


def book_row_to_dict(row: Any) -> dict[str, Any]:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        data = dict(mapping)
    elif hasattr(row, "_asdict"):
        data = row._asdict()
    else:
        data = dict(row)
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "author": data.get("author"),
        "description": data.get("description"),
        "tags": data.get("tags", "[]"),
        "seriesName": data.get("series_name", data.get("seriesName")),
        "seriesIndex": data.get("series_index", data.get("seriesIndex")),
        "coverPath": data.get("cover_path", data.get("coverPath")),
        "coverStatus": data.get("cover_status", data.get("coverStatus")),
        "metadataQuality": data.get("metadata_quality", data.get("metadataQuality")),
        "organized": data.get("organized", False),
        "organizeStatus": data.get("organize_status", data.get("organizeStatus")),
        "normalizedTitle": data.get("normalized_title", data.get("normalizedTitle")),
        "normalizedAuthor": data.get("normalized_author", data.get("normalizedAuthor")),
    }


def resource_row_to_dict(row: Any) -> dict[str, Any]:
    mapping = getattr(row, "_mapping", None)
    data = (
        dict(mapping)
        if mapping is not None
        else (row._asdict() if hasattr(row, "_asdict") else dict(row))
    )
    return {
        "id": data.get("id"),
        "coverPath": data.get("cover_path", data.get("coverPath")),
        "publishedAt": data.get("published_at", data.get("publishedAt")),
        "publisher": data.get("publisher"),
        "language": data.get("language"),
        "isbn": data.get("isbn"),
    }


def lookup_task_is_active(db: Session, task_id: str) -> bool:
    return (
        db.scalar(
            select(MetadataLookupTask.id).where(
                MetadataLookupTask.id == task_id,
                MetadataLookupTask.status.in_(("PENDING", "RUNNING")),
            )
        )
        is not None
    )


def write_metadata_to_files_enabled(db: Session) -> bool:
    value = db.scalar(
        select(OrganizePolicy.write_metadata_to_files).where(
            OrganizePolicy.id == "default"
        )
    )
    return bool(value)


def prefer_local_metadata_enabled(db: Session) -> bool:
    """Read the fresh-baseline local metadata preference."""

    value = db.scalar(
        select(OrganizePolicy.prefer_local_metadata).where(
            OrganizePolicy.id == "default"
        )
    )
    return True if value is None else bool(value)


def update_lookup_task(
    db: Session,
    task_id: str,
    *,
    updated_at: datetime,
    owner_id: str | None = None,
    **values: Any,
) -> bool:
    values = {**values, "updatedAt": updated_at}
    mapped: dict[str, Any] = {}
    for key, value in values.items():
        attr = _LOOKUP_TASK_CAMEL_TO_SNAKE.get(key)
        if attr is None:
            raise KeyError(f"unsupported MetadataLookupTask update field: {key}")
        mapped[attr] = value
    clauses = [
        MetadataLookupTask.id == task_id,
        MetadataLookupTask.status != "CANCELLED",
    ]
    if owner_id is not None:
        clauses.append(MetadataLookupTask.lease_owner_id == owner_id)
        if mapped.get("status") != "RUNNING":
            mapped["lease_owner_id"] = None
            mapped["lease_expires_at"] = None
    result = db.execute(update(MetadataLookupTask).where(*clauses).values(**mapped))
    return bool(result.rowcount)


def recover_stale_lookup_tasks(db: Session, *, now: datetime) -> int:
    result = db.execute(
        update(MetadataLookupTask)
        .where(
            MetadataLookupTask.status == "RUNNING",
            MetadataLookupTask.lease_expires_at <= now,
        )
        .values(
            status="PENDING",
            next_attempt_at=now,
            started_at=None,
            lease_owner_id=None,
            lease_expires_at=None,
            error_summary="任务进程中断，已自动恢复",
            updated_at=now,
        )
    )
    db.flush()
    return int(result.rowcount or 0)


def claim_next_lookup_task(
    db: Session,
    *,
    owner_id: str,
    now: datetime,
    lease_expires_at: datetime,
    organize_job_ready: bool,
) -> dict[str, Any] | None:
    candidate_id = (
        select(MetadataLookupTask.id)
        .where(
            or_(
                (
                    (MetadataLookupTask.status == "PENDING")
                    & or_(
                        MetadataLookupTask.next_attempt_at.is_(None),
                        MetadataLookupTask.next_attempt_at <= now,
                    )
                ),
                (
                    (MetadataLookupTask.status == "RUNNING")
                    & (MetadataLookupTask.lease_expires_at <= now)
                ),
            ),
        )
        .order_by(MetadataLookupTask.created_at.asc(), MetadataLookupTask.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    row = db.execute(
        update(MetadataLookupTask)
        .where(MetadataLookupTask.id == candidate_id)
        .values(
            status="RUNNING",
            started_at=now,
            lease_owner_id=owner_id,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        .returning(MetadataLookupTask)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.organize_job_id and organize_job_ready:
        mark_organize_job_running(db, row.organize_job_id, started_at=now)
    return lookup_task_to_dict(row)


def mark_organize_job_running(
    db: Session, job_id: str, *, started_at: datetime
) -> None:
    values: dict[str, Any] = {
        "status": "RUNNING",
        "summary": "正在调用元数据插件",
        "updated_at": started_at,
    }
    # startedAt exists on the v14 OrganizeJob model; COALESCE preserves an
    # existing stamp.
    values["started_at"] = func.coalesce(OrganizeJob.started_at, started_at)
    db.execute(update(OrganizeJob).where(OrganizeJob.id == job_id).values(**values))


def prepare_provider_execution_start(
    task: dict[str, Any],
    provider: str,
    *,
    execution_id: str,
    attempts: int,
    now: datetime,
) -> PreparedProviderExecutionWrite:
    return PreparedProviderExecutionWrite(
        statement=insert(MetadataProviderExecution).values(
            id=execution_id,
            job_id=task.get("organizeJobId"),
            lookup_task_id=task.get("id"),
            provider_id=provider,
            status="RUNNING",
            attempts=attempts,
            started_at=now,
            created_at=now,
            updated_at=now,
        ),
        execution_id=execution_id,
    )


def prepare_provider_execution_finish(
    execution_id: str | None,
    *,
    status: str,
    raw_result_json: str | None = None,
    error: str | None = None,
    now: datetime,
) -> PreparedProviderExecutionWrite:
    if not execution_id:
        return PreparedProviderExecutionWrite(statement=None, execution_id=None)
    return PreparedProviderExecutionWrite(
        update(MetadataProviderExecution)
        .where(MetadataProviderExecution.id == execution_id)
        .values(
            status=status,
            raw_result_json=raw_result_json,
            error_summary=error,
            finished_at=now,
            updated_at=now,
        ),
        execution_id=execution_id,
    )


def write_prepared_provider_execution(
    db: Session,
    prepared: PreparedProviderExecutionWrite,
) -> str | None:
    if prepared.statement is not None:
        db.execute(prepared.statement)
    return prepared.execution_id


def get_book(db: Session, book_id: str | None) -> dict[str, Any] | None:
    if not book_id:
        return None
    row = db.execute(
        select(LibraryBook, LibraryBookMetadata)
        .outerjoin(
            LibraryBookMetadata,
            LibraryBookMetadata.book_id == LibraryBook.id,
        )
        .where(LibraryBook.id == book_id)
    ).one_or_none()
    if row is None:
        return None
    book, metadata = row
    return {
        "id": book.id,
        "libraryId": book.library_id,
        "title": metadata.title if metadata else "",
        "author": metadata.author if metadata else None,
        "description": metadata.description if metadata else None,
        "tags": "[]",
        "seriesName": metadata.series_name if metadata else None,
        "seriesIndex": metadata.series_index if metadata else None,
        "coverPath": metadata.cover_path if metadata else None,
        "coverStatus": metadata.cover_status if metadata else "PENDING",
        "metadataQuality": metadata.metadata_quality if metadata else 0,
        "normalizedTitle": metadata.normalized_title if metadata else "",
        "normalizedAuthor": metadata.normalized_author if metadata else None,
        "organized": False,
        "organizeStatus": None,
    }


def get_book_organize_state(db: Session, book_id: str | None) -> dict[str, Any] | None:
    if not book_id:
        return None
    row = db.execute(
        select(OrganizeJob.status)
        .where(OrganizeJob.book_id == book_id)
        .order_by(OrganizeJob.updated_at.desc(), OrganizeJob.id.desc())
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    return {
        "organized": row[0] == "APPLIED",
        "organizeStatus": row[0],
    }


def get_resource(db: Session, resource_id: str | None) -> dict[str, Any] | None:
    if not resource_id:
        return None
    row = db.execute(
        select(LibraryReadableResource, LibraryReadableResourceMetadata)
        .outerjoin(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .where(LibraryReadableResource.id == resource_id)
    ).one_or_none()
    if row is None:
        return None
    resource, metadata = row
    return {
        "id": resource.id,
        "format": resource.format,
        "mediaKind": resource.media_kind,
        "coverPath": metadata.cover_path if metadata else None,
        "publishedAt": metadata.published_at if metadata else None,
        "language": metadata.language if metadata else None,
        "isbn": metadata.isbn if metadata else None,
    }


def resource_has_cover(db: Session, resource_id: str) -> bool:
    return (
        db.scalar(
            select(LibraryReadableResourceMetadata.resource_id)
            .select_from(LibraryReadableResourceMetadata)
            .where(
                LibraryReadableResourceMetadata.resource_id == resource_id,
                LibraryReadableResourceMetadata.cover_path.is_not(None),
                LibraryReadableResourceMetadata.cover_path != "",
            )
            .limit(1)
        )
        is not None
    )


def get_import_task_status(db: Session, import_task_id: str | None) -> str | None:
    if not import_task_id:
        return None
    return db.scalar(
        select(LibraryImportTask.state).where(LibraryImportTask.id == import_task_id)
    )


def get_lookup_task_status(db: Session, task_id: str) -> str | None:
    return db.scalar(
        select(MetadataLookupTask.status).where(MetadataLookupTask.id == task_id)
    )


def update_book(db: Session, book_id: str, patch: dict[str, Any]) -> None:
    mapped = {
        _BOOK_METADATA_CAMEL_TO_SNAKE[key]: value
        for key, value in patch.items()
        if key in _BOOK_METADATA_CAMEL_TO_SNAKE
    }
    if not mapped:
        return
    metadata = db.get(LibraryBookMetadata, book_id)
    if metadata is None:
        raise LookupError(book_id)
    for key, value in mapped.items():
        setattr(metadata, key, value)


def clear_remote_cover_if_current(
    db: Session,
    book_id: str,
    *,
    cover_path: str,
    now: datetime,
) -> None:
    db.execute(
        update(LibraryBookMetadata)
        .where(
            LibraryBookMetadata.book_id == book_id,
            LibraryBookMetadata.cover_path == cover_path,
        )
        .values(
            cover_path=None,
            cover_status="PENDING",
            updated_at=now,
        )
    )


def update_resource(db: Session, resource_id: str, patch: dict[str, Any]) -> None:
    values = {
        _RESOURCE_METADATA_CAMEL_TO_SNAKE[key]: value
        for key, value in patch.items()
        if key in _RESOURCE_METADATA_CAMEL_TO_SNAKE
    }
    if not values:
        return
    db.execute(
        update(LibraryReadableResourceMetadata)
        .where(LibraryReadableResourceMetadata.resource_id == resource_id)
        .values(**values)
    )


def mark_book_reviewing(db: Session, book_id: str, *, now: datetime) -> None:
    db.execute(
        update(OrganizeJob)
        .where(
            OrganizeJob.book_id == book_id,
            OrganizeJob.status.in_(("PENDING", "LOOKUP_PENDING", "FAILED")),
        )
        .values(status="REVIEWING", updated_at=now)
    )


def finish_organize_job(
    db: Session,
    job_id: str,
    *,
    status: str,
    summary: str,
    error_summary: str | None = None,
    set_finished_at: bool = True,
    only_if_not_cancelled: bool = False,
    now: datetime,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "summary": summary,
        "error_summary": error_summary,
        "updated_at": now,
    }
    if set_finished_at:
        values["finished_at"] = now
    clause = OrganizeJob.id == job_id
    if only_if_not_cancelled:
        clause = and_(clause, OrganizeJob.status != "CANCELLED")
    db.execute(update(OrganizeJob).where(clause).values(**values))


def mark_organize_job_retry_wait(
    db: Session, job_id: str, *, summary: str, error: str, now: datetime
) -> None:
    db.execute(
        update(OrganizeJob)
        .where(OrganizeJob.id == job_id)
        .values(
            status="LOOKUP_PENDING",
            summary=summary,
            error_summary=error,
            updated_at=now,
        )
    )


def insert_library_metadata(
    db: Session,
    *,
    resource_id: str,
    source: str,
    raw_json: str,
    metadata_id: str,
    now: datetime,
) -> None:
    db.add(
        LibraryBookMetadata(
            id=metadata_id,
            resource_id=resource_id,
            source=source,
            raw_json=raw_json,
            created_at=now,
            updated_at=now,
        )
    )

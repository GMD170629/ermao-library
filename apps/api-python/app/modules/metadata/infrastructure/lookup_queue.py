"""ORM persistence helpers for metadata lookup queue tasks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from time import time_ns
from typing import Any

from sqlalchemy import and_, func, inspect, or_, select, update
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import ImportTask
from app.models.library import LibraryMetadata, LibraryVolume, LibraryWork
from app.models.organize import (
    MetadataLookupTask,
    MetadataProviderExecution,
    OrganizeJob,
    OrganizePolicy,
)

STALE_RUNNING_MINUTES = 10

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
}

_WORK_CAMEL_TO_SNAKE: dict[str, str] = {
    "title": "title",
    "author": "author",
    "description": "description",
    "tags": "tags",
    "seriesName": "series_name",
    "seriesIndex": "series_index",
    "coverPath": "cover_path",
    "coverStatus": "cover_status",
    "normalizedTitle": "normalized_title",
    "normalizedAuthor": "normalized_author",
    "mergeKey": "merge_key",
    "metadataQuality": "metadata_quality",
    "organized": "organized",
    "organizeStatus": "organize_status",
    "updatedAt": "updated_at",
}

_VOLUME_CAMEL_TO_SNAKE: dict[str, str] = {
    "publisher": "publisher",
    "publishedAt": "published_at",
    "language": "language",
    "isbn": "isbn",
    "updatedAt": "updated_at",
}


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


def lookup_task_to_dict(task: MetadataLookupTask) -> dict[str, Any]:
    """Map ORM task attrs to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": task.id,
        "workId": task.work_id,
        "volumeId": task.volume_id,
        "mediaVersionId": task.media_version_id,
        "importTaskId": task.import_task_id,
        "organizeJobId": task.organize_job_id,
        "status": task.status,
        "providerOrder": task.provider_order,
        "attempts": task.attempts,
        "nextAttemptAt": task.next_attempt_at,
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
    """Manual recognition is explicit; legacy and background triggers stay safe."""

    job_id = str(task.get("organizeJobId") or "").strip()
    if not job_id or not _has_table(db, "OrganizeJob"):
        return True
    trigger = db.scalar(select(OrganizeJob.trigger).where(OrganizeJob.id == job_id))
    return str(trigger or "LEGACY").upper() != "MANUAL"


def work_row_to_dict(row: Any) -> dict[str, Any]:
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
        "tags": data.get("tags"),
        "seriesName": data.get("series_name", data.get("seriesName")),
        "seriesIndex": data.get("series_index", data.get("seriesIndex")),
        "coverPath": data.get("cover_path", data.get("coverPath")),
        "coverStatus": data.get("cover_status", data.get("coverStatus")),
        "metadataQuality": data.get("metadata_quality", data.get("metadataQuality")),
        "organized": data.get("organized"),
        "organizeStatus": data.get("organize_status", data.get("organizeStatus")),
        "normalizedTitle": data.get("normalized_title", data.get("normalizedTitle")),
        "normalizedAuthor": data.get("normalized_author", data.get("normalizedAuthor")),
        "mergeKey": data.get("merge_key", data.get("mergeKey")),
    }


def volume_row_to_dict(row: Any) -> dict[str, Any]:
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
    if not _has_table(db, "OrganizePolicy"):
        return False
    columns = {
        str(column.get("name"))
        for column in inspect(db.connection()).get_columns("OrganizePolicy")
    }
    if "writeMetadataToFiles" not in columns:
        return False
    value = db.scalar(
        select(OrganizePolicy.write_metadata_to_files).where(
            OrganizePolicy.id == "default"
        )
    )
    return bool(value)


def prefer_local_metadata_enabled(db: Session) -> bool:
    """Return the safe default when the policy migration is not installed yet."""

    if not _has_table(db, "OrganizePolicy"):
        return True
    columns = {
        str(column.get("name"))
        for column in inspect(db.connection()).get_columns("OrganizePolicy")
    }
    if "preferLocalMetadata" not in columns:
        return True
    value = db.scalar(
        select(OrganizePolicy.prefer_local_metadata).where(
            OrganizePolicy.id == "default"
        )
    )
    return True if value is None else bool(value)


def update_lookup_task(db: Session, task_id: str, **values: Any) -> None:
    values = {**values, "updatedAt": db_timestamp()}
    mapped: dict[str, Any] = {}
    for key, value in values.items():
        attr = _LOOKUP_TASK_CAMEL_TO_SNAKE.get(key)
        if attr is None:
            raise KeyError(f"unsupported MetadataLookupTask update field: {key}")
        mapped[attr] = value
    db.execute(
        update(MetadataLookupTask)
        .where(
            MetadataLookupTask.id == task_id,
            MetadataLookupTask.status != "CANCELLED",
        )
        .values(**mapped)
    )


def recover_stale_lookup_tasks(db: Session) -> int:
    now = db_timestamp()
    cutoff = now - timedelta(minutes=STALE_RUNNING_MINUTES)
    result = db.execute(
        update(MetadataLookupTask)
        .where(
            MetadataLookupTask.status == "RUNNING",
            MetadataLookupTask.started_at < cutoff,
        )
        .values(
            status="PENDING",
            next_attempt_at=now,
            started_at=None,
            error_summary="任务进程中断，已自动恢复",
            updated_at=now,
        )
    )
    db.flush()
    return int(result.rowcount or 0)


def claim_next_lookup_task(db: Session) -> dict[str, Any] | None:
    now = db_timestamp()
    task = db.scalars(
        select(MetadataLookupTask)
        .where(
            MetadataLookupTask.status == "PENDING",
            or_(
                MetadataLookupTask.next_attempt_at.is_(None),
                MetadataLookupTask.next_attempt_at <= now,
            ),
        )
        .order_by(MetadataLookupTask.created_at.asc(), MetadataLookupTask.id.asc())
        .limit(1)
    ).first()
    if task is None:
        return None

    started_at = db_timestamp()
    result = db.execute(
        update(MetadataLookupTask)
        .where(
            MetadataLookupTask.id == task.id,
            MetadataLookupTask.status == "PENDING",
        )
        .values(status="RUNNING", started_at=started_at, updated_at=started_at)
    )
    if result.rowcount and task.organize_job_id and _has_table(db, "OrganizeJob"):
        mark_organize_job_running(db, task.organize_job_id, started_at=started_at)
    payload = lookup_task_to_dict(task)
    payload["status"] = "RUNNING"
    payload["startedAt"] = started_at
    db.flush()
    if not result.rowcount:
        return None
    return payload


def mark_organize_job_running(
    db: Session, job_id: str, *, started_at: datetime
) -> None:
    values: dict[str, Any] = {
        "status": "RUNNING",
        "summary": "正在调用元数据插件",
        "updated_at": started_at,
    }
    # startedAt exists on the v14 OrganizeJob model; COALESCE preserves an existing stamp.
    values["started_at"] = func.coalesce(OrganizeJob.started_at, started_at)
    db.execute(update(OrganizeJob).where(OrganizeJob.id == job_id).values(**values))


def source_table_ready(db: Session) -> bool:
    return _has_table(db, "Source")


def start_provider_execution(
    db: Session, task: dict[str, Any], provider: str
) -> str | None:
    if not _has_table(db, "MetadataProviderExecution"):
        return None
    execution_id = f"py_{time_ns()}"
    now = db_timestamp()
    db.add(
        MetadataProviderExecution(
            id=execution_id,
            job_id=task.get("organizeJobId"),
            lookup_task_id=task.get("id"),
            provider_id=provider,
            status="RUNNING",
            attempts=int(task.get("attempts") or 0) + 1,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    return execution_id


def finish_provider_execution(
    db: Session,
    execution_id: str | None,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    if not execution_id or not _has_table(db, "MetadataProviderExecution"):
        return
    now = db_timestamp()
    db.execute(
        update(MetadataProviderExecution)
        .where(MetadataProviderExecution.id == execution_id)
        .values(
            status=status,
            raw_result_json=json.dumps(result, ensure_ascii=False)
            if result is not None
            else None,
            error_summary=error,
            finished_at=now,
            updated_at=now,
        )
    )
    db.flush()


def get_work(db: Session, work_id: str | None) -> dict[str, Any] | None:
    if not work_id:
        return None
    row = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
            LibraryWork.description,
            LibraryWork.tags,
            LibraryWork.series_name,
            LibraryWork.series_index,
            LibraryWork.cover_path,
            LibraryWork.cover_status,
            LibraryWork.metadata_quality,
            LibraryWork.organized,
            LibraryWork.organize_status,
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
            LibraryWork.merge_key,
        ).where(LibraryWork.id == work_id)
    ).one_or_none()
    return work_row_to_dict(row) if row else None


def get_work_organize_state(db: Session, work_id: str | None) -> dict[str, Any] | None:
    if not work_id:
        return None
    row = db.execute(
        select(LibraryWork.organized, LibraryWork.organize_status).where(
            LibraryWork.id == work_id
        )
    ).one_or_none()
    if row is None:
        return None
    return {
        "organized": row.organized,
        "organizeStatus": row.organize_status,
    }


def get_volume(db: Session, volume_id: str | None) -> dict[str, Any] | None:
    if not volume_id:
        return None
    row = db.execute(
        select(
            LibraryVolume.id,
            LibraryVolume.cover_path,
            LibraryVolume.published_at,
            LibraryVolume.language,
            LibraryVolume.isbn,
        ).where(LibraryVolume.id == volume_id)
    ).one_or_none()
    return volume_row_to_dict(row) if row else None


def volume_has_cover(db: Session, volume_id: str) -> bool:
    return (
        db.scalar(
            select(LibraryVolume.id)
            .where(
                LibraryVolume.id == volume_id,
                LibraryVolume.cover_path.is_not(None),
                LibraryVolume.cover_path != "",
            )
            .limit(1)
        )
        is not None
    )


def get_import_task_status(db: Session, import_task_id: str | None) -> str | None:
    if not import_task_id:
        return None
    return db.scalar(select(ImportTask.status).where(ImportTask.id == import_task_id))


def get_lookup_task_status(db: Session, task_id: str) -> str | None:
    return db.scalar(
        select(MetadataLookupTask.status).where(MetadataLookupTask.id == task_id)
    )


def update_work(db: Session, work_id: str, patch: dict[str, Any]) -> None:
    mapped = {_WORK_CAMEL_TO_SNAKE[key]: value for key, value in patch.items()}
    db.execute(update(LibraryWork).where(LibraryWork.id == work_id).values(**mapped))


def update_volume(db: Session, volume_id: str, patch: dict[str, Any]) -> None:
    mapped = {_VOLUME_CAMEL_TO_SNAKE[key]: value for key, value in patch.items()}
    db.execute(
        update(LibraryVolume).where(LibraryVolume.id == volume_id).values(**mapped)
    )


def mark_work_reviewing(db: Session, work_id: str) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(organized=False, organize_status="REVIEWING", updated_at=db_timestamp())
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
) -> None:
    now = db_timestamp()
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
    db: Session, job_id: str, *, summary: str, error: str
) -> None:
    db.execute(
        update(OrganizeJob)
        .where(OrganizeJob.id == job_id)
        .values(
            status="LOOKUP_PENDING",
            summary=summary,
            error_summary=error,
            updated_at=db_timestamp(),
        )
    )


def insert_library_metadata(
    db: Session,
    *,
    volume_id: str,
    source: str,
    raw_json: str,
) -> None:
    now = db_timestamp()
    db.add(
        LibraryMetadata(
            id=f"py_{time_ns()}",
            volume_id=volume_id,
            source=source,
            raw_json=raw_json,
            created_at=now,
            updated_at=now,
        )
    )

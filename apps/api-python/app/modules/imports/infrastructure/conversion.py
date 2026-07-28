"""ORM persistence for book conversion tasks during import."""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import BookConversionTask, ImportTask
from app.modules.imports.infrastructure.library_queries import (
    get_conversion_by_import_task_id,
)


def get_conversion_row(db: Session, import_task_id: str) -> dict[str, Any] | None:
    return get_conversion_by_import_task_id(db, import_task_id)


def update_conversion_stage(
    db: Session,
    import_task_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    conversion_values: dict[str, Any] | None = None,
    now: Any,
) -> None:
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == import_task_id)
        .values(status="PARSING", progress=progress, message=message, updated_at=now)
    )
    values = {
        "status": status,
        "progress": progress,
        "updatedAt": now,
        **(conversion_values or {}),
    }
    db.execute(
        update(BookConversionTask.__table__)
        .where(BookConversionTask.import_task_id == import_task_id)
        .values(values)
    )


def ensure_conversion_task(
    db: Session,
    import_task_id: str,
    *,
    task_id: str,
    source_path: str,
    fmt: str,
    converter: str,
    options_json: str,
    now: Any,
) -> dict[str, Any]:
    existing = get_conversion_row(db, import_task_id)
    if existing:
        return existing
    values = {
        "id": task_id,
        "importTaskId": import_task_id,
        "mode": "AUTO",
        "sourceFormat": fmt,
        "targetFormat": "EPUB",
        "sourcePath": source_path,
        "converter": converter,
        "optionsJson": options_json,
        "status": "QUEUED",
        "progress": 5,
        "attempts": 0,
        "retryable": 0,
        "createdAt": now,
        "updatedAt": now,
    }
    db.execute(insert(BookConversionTask.__table__).values(values))
    db.flush()
    return get_conversion_row(db, import_task_id) or values


def record_conversion_failure(
    db: Session,
    import_task_id: str,
    *,
    retryable: bool,
    error_code: str,
    summary: str,
    now: Any,
) -> None:
    db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.import_task_id == import_task_id)
        .values(
            status="FAILED",
            progress=100,
            retryable=retryable,
            error_code=error_code,
            error_summary=summary,
            finished_at=now,
            updated_at=now,
        )
    )
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == import_task_id)
        .values(
            error_code=error_code,
            retryable=retryable,
            error_summary=summary,
            updated_at=now,
        )
    )

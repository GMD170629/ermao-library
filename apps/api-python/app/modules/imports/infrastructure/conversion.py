"""ORM persistence for idempotent book conversions during import."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.import_pipeline import BookConversionTask, ImportTask
from app.models.library import LibraryFile
from app.modules.imports.application.dto import ConversionProgressTaskDTO


class ConversionTaskConflict(RuntimeError):
    """Raised when a conversion idempotency scope cannot be safely reconciled."""


def _record(task: BookConversionTask) -> ConversionProgressTaskDTO:
    return ConversionProgressTaskDTO(
        id=task.id,
        import_task_id=task.import_task_id,
        idempotency_key=task.idempotency_key,
        status=task.status,
        attempts=task.attempts,
        started_at=task.started_at,
    )


def _by_import_task(db: Session, import_task_id: str) -> BookConversionTask | None:
    return db.scalar(
        select(BookConversionTask).where(
            BookConversionTask.import_task_id == import_task_id
        )
    )


def _by_idempotency_key(db: Session, idempotency_key: str) -> BookConversionTask | None:
    return db.scalar(
        select(BookConversionTask).where(
            BookConversionTask.idempotency_key == idempotency_key
        )
    )


def resolve_source_volume_id(
    db: Session, import_task_id: str, source_path: str
) -> str | None:
    import_task = db.get(ImportTask, import_task_id)
    if import_task is not None and import_task.volume_id:
        return str(import_task.volume_id)
    volume_id = db.scalar(
        select(LibraryFile.volume_id).where(LibraryFile.path == source_path).limit(1)
    )
    if import_task is not None and volume_id:
        import_task.volume_id = str(volume_id)
        db.flush()
    return str(volume_id) if volume_id else None


def ensure_conversion_task(
    db: Session,
    import_task_id: str,
    *,
    task_id: str,
    source_volume_id: str,
    source_hash: str,
    idempotency_key: str,
    source_path: str,
    fmt: str,
    target_format: str,
    converter: str,
    options_json: str,
    now: object,
) -> ConversionProgressTaskDTO:
    """Return the single task for a source-volume/hash/target conversion scope.

    A retried import may have a different ``ImportTask`` id. The unique conversion
    task remains owned by the first importer and is reused by idempotency key. If
    the same import task is deliberately rerun after its source content changes,
    its conversion row is reset to the new scope without altering old derived
    volumes.
    """

    scoped = _by_idempotency_key(db, idempotency_key)
    if scoped is not None:
        return _record(scoped)

    current = _by_import_task(db, import_task_id)
    if current is not None:
        current.source_volume_id = source_volume_id
        current.derived_volume_id = None
        current.idempotency_key = idempotency_key
        current.source_format = fmt
        current.target_format = target_format
        current.source_path = source_path
        current.output_path = None
        current.source_hash = source_hash
        current.converter = converter
        current.converter_version = None
        current.options_json = options_json
        current.status = "QUEUED"
        current.progress = 5
        current.attempts = 0
        current.retryable = False
        current.error_code = None
        current.error_summary = None
        current.started_at = None
        current.finished_at = None
        current.updated_at = now
        db.flush()
        return _record(current)

    task = BookConversionTask(
        id=task_id,
        import_task_id=import_task_id,
        source_volume_id=source_volume_id,
        idempotency_key=idempotency_key,
        mode="AUTO",
        source_format=fmt,
        target_format=target_format,
        source_path=source_path,
        source_hash=source_hash,
        converter=converter,
        options_json=options_json,
        status="QUEUED",
        progress=5,
        attempts=0,
        retryable=False,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError as exc:
        winner = _by_idempotency_key(db, idempotency_key) or _by_import_task(
            db, import_task_id
        )
        if winner is None:
            raise ConversionTaskConflict(
                "conversion idempotency scope conflicted without a persisted winner"
            ) from exc
        return _record(winner)
    return _record(task)


def update_conversion_stage(
    db: Session,
    import_task_id: str,
    conversion_task_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    conversion_values: dict[str, object] | None = None,
    now: object,
) -> None:
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == import_task_id)
        .values(status="PARSING", progress=progress, message=message, updated_at=now)
    )
    task = db.get(BookConversionTask, conversion_task_id)
    if task is None:
        raise ConversionTaskConflict("conversion task disappeared during processing")
    task.status = status
    task.progress = progress
    task.updated_at = cast(datetime, now)
    for field, value in (conversion_values or {}).items():
        if field == "sourceFormat":
            task.source_format = str(value)
        elif field == "sourceHash":
            task.source_hash = None if value is None else str(value)
        elif field == "outputPath":
            task.output_path = None if value is None else str(value)
        elif field == "converter":
            task.converter = str(value)
        elif field == "converterVersion":
            task.converter_version = None if value is None else str(value)
        elif field == "optionsJson":
            task.options_json = str(value)
        elif field == "attempts":
            task.attempts = int(cast(int | str, value))
        elif field == "retryable":
            task.retryable = bool(value)
        elif field == "errorCode":
            task.error_code = None if value is None else str(value)
        elif field == "errorSummary":
            task.error_summary = None if value is None else str(value)
        elif field == "startedAt":
            task.started_at = cast(datetime | None, value)
        elif field == "finishedAt":
            task.finished_at = cast(datetime | None, value)
        else:
            raise ValueError(f"unsupported conversion task field: {field}")
    db.flush()


def bind_derived_volume(
    db: Session,
    *,
    idempotency_key: str,
    derived_volume_id: str,
    now: object,
) -> None:
    task = _by_idempotency_key(db, idempotency_key)
    if task is None:
        raise ConversionTaskConflict("conversion task disappeared before publication")
    if task.derived_volume_id not in {None, derived_volume_id}:
        raise ConversionTaskConflict(
            "conversion idempotency scope already points to another derived volume"
        )
    task.derived_volume_id = derived_volume_id
    task.updated_at = now
    db.flush()


def record_conversion_failure(
    db: Session,
    import_task_id: str,
    conversion_task_id: str,
    *,
    retryable: bool,
    error_code: str,
    summary: str,
    now: object,
) -> None:
    db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.id == conversion_task_id)
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

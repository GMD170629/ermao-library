"""ORM persistence for idempotent book conversions during import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.import_pipeline import BookConversionTask, ImportTask
from app.models.library import LibraryFile
from app.modules.imports.application.dto import ConversionProgressTaskDTO


class ConversionTaskConflict(RuntimeError):
    """Raised when a conversion idempotency scope cannot be safely reconciled."""


@dataclass(frozen=True, slots=True)
class ConversionTaskProjection:
    scoped: ConversionProgressTaskDTO | None
    current: ConversionProgressTaskDTO | None


@dataclass(frozen=True, slots=True)
class PreparedConversionTaskWrite:
    mode: Literal["reuse", "update", "insert"]
    result: ConversionProgressTaskDTO
    task_id: str
    import_task_id: str
    source_volume_id: str
    source_hash: str
    idempotency_key: str
    source_path: str
    source_format: str
    converter: str
    options_json: str
    now: object
    reset_values: dict[str, object]


@dataclass(frozen=True, slots=True)
class DerivedVolumeBindingProjection:
    task_id: str
    derived_volume_id: str | None


@dataclass(frozen=True, slots=True)
class PreparedDerivedVolumeBinding:
    task_id: str
    derived_volume_id: str
    updated_at: object


@dataclass(frozen=True, slots=True)
class PreparedConversionStageWrite:
    import_task_id: str
    conversion_task_id: str
    import_task_values: dict[str, object]
    conversion_task_values: dict[str, object]


@dataclass(frozen=True, slots=True)
class PreparedConversionFailureWrite:
    import_task_id: str
    conversion_task_id: str
    import_task_values: dict[str, object]
    conversion_task_values: dict[str, object]


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


def load_source_volume_id(
    db: Session, import_task_id: str, source_path: str
) -> str | None:
    import_task = db.get(ImportTask, import_task_id)
    if import_task is not None and import_task.volume_id:
        return str(import_task.volume_id)
    volume_id = db.scalar(
        select(LibraryFile.volume_id).where(LibraryFile.path == source_path).limit(1)
    )
    return str(volume_id) if volume_id else None


def link_source_volume_id(
    db: Session, import_task_id: str, source_volume_id: str
) -> None:
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == import_task_id)
        .values(volume_id=source_volume_id)
    )


def load_conversion_task_projection(
    db: Session,
    *,
    import_task_id: str,
    idempotency_key: str,
) -> ConversionTaskProjection:
    scoped = _by_idempotency_key(db, idempotency_key)
    current = None if scoped is not None else _by_import_task(db, import_task_id)
    return ConversionTaskProjection(
        scoped=_record(scoped) if scoped is not None else None,
        current=_record(current) if current is not None else None,
    )


def prepare_conversion_task_write(
    projection: ConversionTaskProjection,
    *,
    import_task_id: str,
    task_id: str,
    source_volume_id: str,
    source_hash: str,
    idempotency_key: str,
    source_path: str,
    source_format: str,
    converter: str,
    options_json: str,
    now: object,
) -> PreparedConversionTaskWrite:
    if projection.scoped is not None:
        mode: Literal["reuse", "update", "insert"] = "reuse"
        result = projection.scoped
    elif projection.current is not None:
        mode = "update"
        result = ConversionProgressTaskDTO(
            id=projection.current.id,
            import_task_id=import_task_id,
            idempotency_key=idempotency_key,
            status="QUEUED",
            attempts=0,
            started_at=None,
        )
    else:
        mode = "insert"
        result = ConversionProgressTaskDTO(
            id=task_id,
            import_task_id=import_task_id,
            idempotency_key=idempotency_key,
            status="QUEUED",
            attempts=0,
            started_at=None,
        )
    reset_values = {
        "source_volume_id": source_volume_id,
        "derived_volume_id": None,
        "idempotency_key": idempotency_key,
        "source_format": source_format,
        "target_format": "EPUB",
        "source_path": source_path,
        "output_path": None,
        "source_hash": source_hash,
        "converter": converter,
        "converter_version": None,
        "options_json": options_json,
        "status": "QUEUED",
        "progress": 5,
        "attempts": 0,
        "retryable": False,
        "error_code": None,
        "error_summary": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": now,
    }
    return PreparedConversionTaskWrite(
        mode=mode,
        result=result,
        task_id=result.id,
        import_task_id=import_task_id,
        source_volume_id=source_volume_id,
        source_hash=source_hash,
        idempotency_key=idempotency_key,
        source_path=source_path,
        source_format=source_format,
        converter=converter,
        options_json=options_json,
        now=now,
        reset_values=reset_values,
    )


def write_reused_conversion_task(
    db: Session,
    prepared: PreparedConversionTaskWrite,
) -> None:
    link_source_volume_id(
        db,
        prepared.import_task_id,
        prepared.source_volume_id,
    )


def write_updated_conversion_task(
    db: Session,
    prepared: PreparedConversionTaskWrite,
) -> None:
    link_source_volume_id(db, prepared.import_task_id, prepared.source_volume_id)
    db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.id == prepared.task_id)
        .values(**prepared.reset_values)
    )


def write_inserted_conversion_task(
    db: Session,
    prepared: PreparedConversionTaskWrite,
) -> None:
    link_source_volume_id(db, prepared.import_task_id, prepared.source_volume_id)
    inserted = db.execute(
        sqlite_insert(BookConversionTask)
        .values(
            id=prepared.task_id,
            import_task_id=prepared.import_task_id,
            mode="AUTO",
            created_at=prepared.now,
            **prepared.reset_values,
        )
        .on_conflict_do_nothing()
    )
    if not inserted.rowcount:
        raise ConversionTaskConflict("conversion idempotency scope changed")


def prepare_conversion_stage_write(
    import_task_id: str,
    conversion_task_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    conversion_values: dict[str, object] | None = None,
    now: object,
) -> PreparedConversionStageWrite:
    conversion_task_values: dict[str, object] = {
        "status": status,
        "progress": progress,
        "updated_at": cast(datetime, now),
    }
    field_mapping = {
        "sourceFormat": "source_format",
        "sourceHash": "source_hash",
        "outputPath": "output_path",
        "converter": "converter",
        "converterVersion": "converter_version",
        "optionsJson": "options_json",
        "attempts": "attempts",
        "retryable": "retryable",
        "errorCode": "error_code",
        "errorSummary": "error_summary",
        "startedAt": "started_at",
        "finishedAt": "finished_at",
    }
    nullable_strings = {
        "sourceHash",
        "outputPath",
        "converterVersion",
        "errorCode",
        "errorSummary",
    }
    for field, value in (conversion_values or {}).items():
        target = field_mapping.get(field)
        if target is None:
            raise ValueError(f"unsupported conversion task field: {field}")
        if field in nullable_strings:
            conversion_task_values[target] = None if value is None else str(value)
        elif field in {"sourceFormat", "converter", "optionsJson"}:
            conversion_task_values[target] = str(value)
        elif field == "attempts":
            conversion_task_values[target] = int(cast(int | str, value))
        elif field == "retryable":
            conversion_task_values[target] = bool(value)
        else:
            conversion_task_values[target] = value
    return PreparedConversionStageWrite(
        import_task_id=import_task_id,
        conversion_task_id=conversion_task_id,
        import_task_values={
            "status": "PARSING",
            "progress": progress,
            "message": message,
            "updated_at": now,
        },
        conversion_task_values=conversion_task_values,
    )


def write_conversion_stage(
    db: Session,
    prepared: PreparedConversionStageWrite,
) -> None:
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == prepared.import_task_id)
        .values(**prepared.import_task_values)
    )
    result = db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.id == prepared.conversion_task_id)
        .values(**prepared.conversion_task_values)
    )
    if not result.rowcount:
        raise ConversionTaskConflict("conversion task disappeared during processing")


def load_derived_volume_binding_projection(
    db: Session,
    *,
    idempotency_key: str,
) -> DerivedVolumeBindingProjection | None:
    row = db.execute(
        select(BookConversionTask.id, BookConversionTask.derived_volume_id).where(
            BookConversionTask.idempotency_key == idempotency_key
        )
    ).one_or_none()
    if row is None:
        return None
    return DerivedVolumeBindingProjection(
        task_id=str(row.id),
        derived_volume_id=(
            str(row.derived_volume_id) if row.derived_volume_id is not None else None
        ),
    )


def prepare_derived_volume_binding(
    projection: DerivedVolumeBindingProjection | None,
    *,
    derived_volume_id: str,
    now: object,
) -> PreparedDerivedVolumeBinding:
    if projection is None:
        raise ConversionTaskConflict("conversion task disappeared before publication")
    if projection.derived_volume_id not in {None, derived_volume_id}:
        raise ConversionTaskConflict(
            "conversion idempotency scope already points to another derived volume"
        )
    return PreparedDerivedVolumeBinding(
        task_id=projection.task_id,
        derived_volume_id=derived_volume_id,
        updated_at=now,
    )


def write_derived_volume_binding(
    db: Session,
    prepared: PreparedDerivedVolumeBinding,
) -> None:
    result = db.execute(
        update(BookConversionTask)
        .where(
            BookConversionTask.id == prepared.task_id,
            or_(
                BookConversionTask.derived_volume_id.is_(None),
                BookConversionTask.derived_volume_id == prepared.derived_volume_id,
            ),
        )
        .values(
            derived_volume_id=prepared.derived_volume_id,
            updated_at=prepared.updated_at,
        )
    )
    if not result.rowcount:
        raise ConversionTaskConflict(
            "conversion idempotency scope changed before publication"
        )


def prepare_conversion_failure_write(
    import_task_id: str,
    conversion_task_id: str,
    *,
    retryable: bool,
    error_code: str,
    summary: str,
    now: object,
) -> PreparedConversionFailureWrite:
    return PreparedConversionFailureWrite(
        import_task_id=import_task_id,
        conversion_task_id=conversion_task_id,
        conversion_task_values={
            "status": "FAILED",
            "progress": 100,
            "retryable": retryable,
            "error_code": error_code,
            "error_summary": summary,
            "finished_at": now,
            "updated_at": now,
        },
        import_task_values={
            "error_code": error_code,
            "retryable": retryable,
            "error_summary": summary,
            "updated_at": now,
        },
    )


def write_conversion_failure(
    db: Session,
    prepared: PreparedConversionFailureWrite,
) -> None:
    db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.id == prepared.conversion_task_id)
        .values(**prepared.conversion_task_values)
    )
    db.execute(
        update(ImportTask)
        .where(ImportTask.id == prepared.import_task_id)
        .values(**prepared.import_task_values)
    )

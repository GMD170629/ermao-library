"""ORM persistence for recoverable metadata file writeback operations."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from time import time_ns
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import ImportAsset, ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import (
    MetadataWritebackOperation,
    MetadataWritebackTarget,
    OrganizePolicy,
)

MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (30, 120)


def _id(prefix: str) -> str:
    return f"{prefix}_{time_ns()}"


def write_metadata_to_files_enabled(db: Session) -> bool:
    value = db.scalar(
        select(OrganizePolicy.write_metadata_to_files).where(
            OrganizePolicy.id == "default"
        )
    )
    return bool(value)


def _tags(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return (
        [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, list)
        else []
    )


def _authors(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(" / ") if part.strip()]


def enqueue_writeback(
    db: Session,
    *,
    work_id: str,
    media_version_id: str,
    source: str,
    lookup_task_id: str | None = None,
    volume_id: str | None = None,
) -> str:
    work = db.scalar(select(LibraryWork).where(LibraryWork.id == work_id))
    media_version = db.scalar(
        select(LibraryMediaVersion).where(
            LibraryMediaVersion.id == media_version_id,
            LibraryMediaVersion.work_id == work_id,
        )
    )
    if work is None or media_version is None:
        raise ValueError("作品或媒介版本不存在")
    now = db_timestamp()
    operation = MetadataWritebackOperation(
        id=_id("metadata_writeback"),
        work_id=work_id,
        media_version_id=media_version_id,
        lookup_task_id=lookup_task_id,
        source=source,
        status="PENDING",
        total_targets=0,
        completed_targets=0,
        warning_targets=0,
        created_at=now,
        updated_at=now,
    )
    db.add(operation)
    file_query = (
        select(LibraryFile, LibraryVolume)
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .where(
            LibraryVolume.media_version_id == media_version_id,
            LibraryVolume.hidden.is_(False),
        )
    )
    if volume_id is not None:
        file_query = file_query.where(LibraryVolume.id == volume_id)
    rows = db.execute(
        file_query.order_by(
            LibraryVolume.sort_order.asc(), LibraryFile.sort_order.asc()
        )
    ).all()
    files_by_volume: dict[str, tuple[LibraryVolume, list[LibraryFile]]] = {}
    for file, volume in rows:
        entry = files_by_volume.setdefault(volume.id, (volume, []))
        entry[1].append(file)
    seen: set[Path] = set()
    for volume, files in files_by_volume.values():
        import_tasks = db.execute(
            select(ImportTask.id, ImportTask.source_path)
            .where(
                ImportTask.volume_id == volume.id,
                ImportTask.status == "COMPLETED",
            )
            .order_by(ImportTask.created_at.asc())
        ).all()
        source_values = list(
            dict.fromkeys(str(source_path) for _task_id, source_path in import_tasks)
        )
        directory_task_ids = [
            task_id
            for task_id, source_path in import_tasks
            if Path(str(source_path)).expanduser().is_dir()
        ]
        if directory_task_ids:
            asset_sources = db.scalars(
                select(ImportAsset.source_path)
                .where(ImportAsset.import_task_id.in_(directory_task_ids))
                .order_by(ImportAsset.sort_order.asc())
            ).all()
            source_values.extend(
                value
                for value in dict.fromkeys(str(path) for path in asset_sources)
                if value not in source_values
            )
        if not source_values:
            source_values = [file.path for file in files]
        for source_value in source_values:
            target_path = Path(source_value).expanduser().resolve()
            if target_path in seen:
                continue
            seen.add(target_path)
            matching_file = next(
                (
                    file
                    for file in files
                    if Path(file.path).expanduser().resolve() == target_path
                ),
                None,
            )
            try:
                target_stat = target_path.stat() if target_path.is_file() else None
            except OSError:
                target_stat = None
            payload = {
                "title": work.title,
                "volumeTitle": volume.title,
                "authors": _authors(work.author),
                "description": work.description or volume.description,
                "subjects": _tags(work.tags),
                "seriesName": work.series_name,
                "volumeIndex": volume.volume_index,
                "language": volume.language,
                "publisher": volume.publisher,
                "publishedAt": volume.published_at.isoformat()
                if volume.published_at
                else None,
                "identifier": volume.identifier,
                "isbn": volume.isbn,
                "coverPath": work.cover_path or volume.cover_path,
                "sourceSize": target_stat.st_size if target_stat else None,
                "sourceMtimeMs": int(target_stat.st_mtime * 1000)
                if target_stat
                else None,
            }
            target_key = hashlib.sha256(str(target_path).encode("utf-8")).hexdigest()
            db.add(
                MetadataWritebackTarget(
                    id=_id("metadata_writeback_target"),
                    operation_id=operation.id,
                    library_file_id=matching_file.id if matching_file else None,
                    target_key=target_key,
                    source_path=str(target_path),
                    format=(
                        target_path.suffix.removeprefix(".") or "DIRECTORY"
                    ).upper(),
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    status="PENDING",
                    attempts=0,
                    written_fields_json="[]",
                    created_at=now,
                    updated_at=now,
                )
            )
            operation.total_targets += 1
    if operation.total_targets == 0:
        operation.status = "COMPLETED_WITH_WARNINGS"
        operation.warning_targets = 1
        operation.finished_at = now
    db.flush()
    return operation.id


def operation_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    operation = db.scalar(
        select(MetadataWritebackOperation).where(
            MetadataWritebackOperation.id == operation_id
        )
    )
    if operation is None:
        return None
    targets = db.scalars(
        select(MetadataWritebackTarget)
        .where(MetadataWritebackTarget.operation_id == operation_id)
        .order_by(MetadataWritebackTarget.created_at.asc())
    ).all()
    return {
        "id": operation.id,
        "status": operation.status,
        "totalTargets": operation.total_targets,
        "completedTargets": operation.completed_targets,
        "warningTargets": operation.warning_targets,
        "targets": [
            {
                "format": target.format,
                "status": target.status,
                "writtenFields": json.loads(target.written_fields_json or "[]"),
                "warningCode": target.warning_code,
                "errorSummary": _public_target_summary(target),
            }
            for target in targets
        ],
        "createdAt": operation.created_at,
        "updatedAt": operation.updated_at,
        "finishedAt": operation.finished_at,
    }


def _public_target_summary(target: MetadataWritebackTarget) -> str | None:
    if target.warning_code == "SIDECAR_FALLBACK":
        return "已生成旁车 OPF"
    if target.warning_code:
        return "文件元数据写回失败"
    return None


def operation_view_for_lookup_task(
    db: Session, lookup_task_id: str | None
) -> dict[str, Any] | None:
    if not lookup_task_id:
        return None
    operation_id = db.scalar(
        select(MetadataWritebackOperation.id)
        .where(MetadataWritebackOperation.lookup_task_id == lookup_task_id)
        .order_by(MetadataWritebackOperation.created_at.desc())
        .limit(1)
    )
    return operation_view(db, operation_id) if operation_id else None


def operation_work_id(db: Session, operation_id: str) -> str | None:
    return db.scalar(
        select(MetadataWritebackOperation.work_id).where(
            MetadataWritebackOperation.id == operation_id
        )
    )


def claim_next_target(db: Session) -> dict[str, Any] | None:
    now = db_timestamp()
    target = db.scalars(
        select(MetadataWritebackTarget)
        .where(
            or_(
                MetadataWritebackTarget.status == "PREPARED",
                (
                    (MetadataWritebackTarget.status == "PENDING")
                    & or_(
                        MetadataWritebackTarget.next_attempt_at.is_(None),
                        MetadataWritebackTarget.next_attempt_at <= now,
                    )
                ),
            )
        )
        .order_by(MetadataWritebackTarget.created_at.asc())
        .limit(1)
    ).first()
    if target is None:
        return None
    if target.status == "PENDING":
        target.status = "RUNNING"
        target.attempts += 1
        target.updated_at = now
        operation = db.get(MetadataWritebackOperation, target.operation_id)
        if operation is not None:
            operation.status = "RUNNING"
            operation.updated_at = now
    db.flush()
    return {
        "id": target.id,
        "operationId": target.operation_id,
        "libraryFileId": target.library_file_id,
        "sourcePath": target.source_path,
        "format": target.format,
        "payload": json.loads(target.payload_json),
        "status": target.status,
        "attempts": target.attempts,
        "preparedPath": target.prepared_path,
        "outputHash": target.output_hash,
        "warningCode": target.warning_code,
    }


def recover_interrupted_targets(db: Session) -> int:
    recovered_count = int(
        db.scalar(
            select(func.count()).where(MetadataWritebackTarget.status == "RUNNING")
        )
        or 0
    )
    db.execute(
        update(MetadataWritebackTarget)
        .where(MetadataWritebackTarget.status == "RUNNING")
        .values(
            status="PENDING",
            next_attempt_at=None,
            updated_at=db_timestamp(),
        )
    )
    db.execute(
        update(MetadataWritebackOperation)
        .where(MetadataWritebackOperation.status == "RUNNING")
        .values(status="PENDING", updated_at=db_timestamp())
    )
    return recovered_count


def mark_prepared(
    db: Session,
    target_id: str,
    *,
    prepared_path: str,
    output_hash: str,
    warning_code: str | None,
) -> None:
    db.execute(
        update(MetadataWritebackTarget)
        .where(MetadataWritebackTarget.id == target_id)
        .values(
            status="PREPARED",
            prepared_path=prepared_path,
            output_hash=output_hash,
            warning_code=warning_code,
            updated_at=db_timestamp(),
        )
    )


def _refresh_operation(db: Session, operation_id: str) -> None:
    db.flush()
    counts: dict[str, int] = {
        str(status): int(count)
        for status, count in db.execute(
            select(MetadataWritebackTarget.status, func.count())
            .where(MetadataWritebackTarget.operation_id == operation_id)
            .group_by(MetadataWritebackTarget.status)
        ).all()
    }
    operation = db.get(MetadataWritebackOperation, operation_id)
    if operation is None:
        return
    complete = int(counts.get("COMPLETED", 0))
    warnings = int(counts.get("WARNING", 0))
    operation.completed_targets = complete
    operation.warning_targets = warnings
    operation.updated_at = db_timestamp()
    terminal = complete + warnings >= operation.total_targets
    if terminal:
        operation.status = "COMPLETED_WITH_WARNINGS" if warnings else "COMPLETED"
        operation.finished_at = db_timestamp()
    else:
        operation.status = "RUNNING"


def complete_target(
    db: Session,
    target_id: str,
    *,
    written_fields: tuple[str, ...],
    size_bytes: int | None,
    mtime_ms: int | None,
    warning_code: str | None = None,
) -> None:
    target = db.get(MetadataWritebackTarget, target_id)
    if target is None:
        return
    target.status = "WARNING" if warning_code else "COMPLETED"
    target.written_fields_json = json.dumps(written_fields, ensure_ascii=False)
    target.prepared_path = None
    target.warning_code = warning_code
    target.error_summary = "已生成旁车 OPF" if warning_code else None
    target.finished_at = db_timestamp()
    target.updated_at = db_timestamp()
    if target.library_file_id and size_bytes is not None and mtime_ms is not None:
        db.execute(
            update(LibraryFile)
            .where(LibraryFile.id == target.library_file_id)
            .values(
                size_bytes=size_bytes,
                mtime_ms=mtime_ms,
                hash_status="PARTIAL_PENDING",
                full_hash=None,
                updated_at=db_timestamp(),
            )
        )
    _refresh_operation(db, target.operation_id)


def fail_target(db: Session, target_id: str, *, code: str, summary: str) -> None:
    target = db.get(MetadataWritebackTarget, target_id)
    if target is None:
        return
    target.prepared_path = None
    target.output_hash = None
    target.error_summary = summary[:800]
    target.updated_at = db_timestamp()
    if target.attempts >= MAX_ATTEMPTS:
        target.status = "WARNING"
        target.warning_code = code
        target.finished_at = db_timestamp()
    else:
        target.status = "PENDING"
        target.next_attempt_at = db_timestamp() + timedelta(
            seconds=RETRY_DELAYS_SECONDS[max(0, target.attempts - 1)]
        )
    _refresh_operation(db, target.operation_id)

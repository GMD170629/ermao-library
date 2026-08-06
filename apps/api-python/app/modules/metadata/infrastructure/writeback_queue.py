"""ORM persistence for recoverable metadata file writeback operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    MetadataOpfQueueState,
    MetadataWritebackOperation,
    MetadataWritebackTarget,
    OrganizePolicy,
)

DEFAULT_MAX_PENDING_TARGETS = 50_000
QUEUE_STATE_ID = "default"


@dataclass(frozen=True, slots=True)
class EnqueueWritebackResult:
    operation_id: str | None
    requested_targets: int
    outcome: str


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
    max_pending_targets: int = DEFAULT_MAX_PENDING_TARGETS,
) -> EnqueueWritebackResult:
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
    targets: list[dict[str, object]] = []
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
                "seriesIndex": work.series_index,
                "volumeIndex": volume.volume_index,
                "narrators": _authors(volume.narrator),
                "abridged": volume.abridged,
                "language": volume.language,
                "publisher": volume.publisher,
                "publishedAt": volume.published_at.isoformat()
                if volume.published_at
                else None,
                "identifier": volume.identifier,
                "isbn": volume.isbn,
                "coverPath": volume.cover_path or work.cover_path,
                "sourceSize": target_stat.st_size if target_stat else None,
                "sourceMtimeMs": int(target_stat.st_mtime * 1000)
                if target_stat
                else None,
            }
            target_key = hashlib.sha256(str(target_path).encode("utf-8")).hexdigest()
            targets.append(
                {
                    "id": _id("metadata_writeback_target"),
                    "library_file_id": matching_file.id if matching_file else None,
                    "target_key": target_key,
                    "source_path": str(target_path),
                    "format": (
                        target_path.suffix.removeprefix(".") or "DIRECTORY"
                    ).upper(),
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                }
            )
            if len(targets) > max_pending_targets:
                return EnqueueWritebackResult(
                    None, len(targets), "QUEUE_FULL"
                )
    if not targets:
        return EnqueueWritebackResult(None, 0, "NO_TARGETS")
    db.execute(
        sqlite_insert(MetadataOpfQueueState)
        .values(id=QUEUE_STATE_ID, pending_targets=0, updated_at=now)
        .on_conflict_do_nothing(index_elements=[MetadataOpfQueueState.id])
    )
    reserved = db.execute(
        update(MetadataOpfQueueState)
        .where(
            MetadataOpfQueueState.id == QUEUE_STATE_ID,
            MetadataOpfQueueState.pending_targets
            <= max_pending_targets - len(targets),
        )
        .values(
            pending_targets=MetadataOpfQueueState.pending_targets + len(targets),
            updated_at=now,
        )
    )
    if not reserved.rowcount:
        return EnqueueWritebackResult(None, len(targets), "QUEUE_FULL")
    operation = MetadataWritebackOperation(
        id=_id("metadata_writeback"),
        work_id=work_id,
        media_version_id=media_version_id,
        lookup_task_id=lookup_task_id,
        source=source,
        status="PENDING",
        total_targets=len(targets),
        completed_targets=0,
        warning_targets=0,
        created_at=now,
        updated_at=now,
    )
    db.add(operation)
    for target in targets:
        db.add(
            MetadataWritebackTarget(
                operation_id=operation.id,
                status="PENDING",
                attempts=0,
                written_fields_json="[]",
                created_at=now,
                updated_at=now,
                **target,
            )
        )
    db.flush()
    return EnqueueWritebackResult(operation.id, len(targets), "QUEUED")


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
        return "旁车 OPF 保存失败"
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


def discard_operations(db: Session, operation_ids: tuple[str, ...]) -> int:
    """Atomically discard a newly admitted batch when a later scope cannot fit."""
    if not operation_ids:
        return 0
    target_count = int(
        db.scalar(
            select(func.count())
            .select_from(MetadataWritebackTarget)
            .where(MetadataWritebackTarget.operation_id.in_(operation_ids))
        )
        or 0
    )
    db.execute(
        delete(MetadataWritebackTarget).where(
            MetadataWritebackTarget.operation_id.in_(operation_ids)
        )
    )
    db.execute(
        delete(MetadataWritebackOperation).where(
            MetadataWritebackOperation.id.in_(operation_ids)
        )
    )
    if target_count:
        db.execute(
            update(MetadataOpfQueueState)
            .where(MetadataOpfQueueState.id == QUEUE_STATE_ID)
            .values(
                pending_targets=func.max(
                    0, MetadataOpfQueueState.pending_targets - target_count
                ),
                updated_at=db_timestamp(),
            )
        )
    return target_count


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
    reconcile_queue_state(db)
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


def _release_target(db: Session, target: MetadataWritebackTarget) -> None:
    operation_id = target.operation_id
    db.delete(target)
    db.execute(
        update(MetadataOpfQueueState)
        .where(
            MetadataOpfQueueState.id == QUEUE_STATE_ID,
            MetadataOpfQueueState.pending_targets > 0,
        )
        .values(
            pending_targets=MetadataOpfQueueState.pending_targets - 1,
            updated_at=db_timestamp(),
        )
    )
    db.flush()
    remaining = db.scalar(
        select(func.count()).where(
            MetadataWritebackTarget.operation_id == operation_id
        )
    )
    if not remaining:
        db.execute(
            delete(MetadataWritebackOperation).where(
                MetadataWritebackOperation.id == operation_id
            )
        )


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
    _release_target(db, target)


def fail_target(db: Session, target_id: str, *, code: str, summary: str) -> None:
    target = db.get(MetadataWritebackTarget, target_id)
    if target is None:
        return
    _release_target(db, target)


def reconcile_queue_state(db: Session) -> int:
    active_count = int(
        db.scalar(select(func.count()).select_from(MetadataWritebackTarget)) or 0
    )
    now = db_timestamp()
    db.execute(
        sqlite_insert(MetadataOpfQueueState)
        .values(id=QUEUE_STATE_ID, pending_targets=active_count, updated_at=now)
        .on_conflict_do_update(
            index_elements=[MetadataOpfQueueState.id],
            set_={
                MetadataOpfQueueState.pending_targets: active_count,
                MetadataOpfQueueState.updated_at: now,
            },
        )
    )
    return active_count


def cleanup_terminal_history(db: Session, *, batch_size: int = 1_000) -> int:
    terminal_ids = list(
        db.scalars(
            select(MetadataWritebackTarget.id)
            .where(MetadataWritebackTarget.status.in_(("COMPLETED", "WARNING")))
            .order_by(MetadataWritebackTarget.created_at.asc())
            .limit(batch_size)
        ).all()
    )
    if terminal_ids:
        db.execute(
            delete(MetadataWritebackTarget).where(
                MetadataWritebackTarget.id.in_(terminal_ids)
            )
        )
    orphan_operation_ids = list(
        db.scalars(
            select(MetadataWritebackOperation.id)
            .outerjoin(
                MetadataWritebackTarget,
                MetadataWritebackTarget.operation_id == MetadataWritebackOperation.id,
            )
            .where(MetadataWritebackTarget.id.is_(None))
            .limit(batch_size)
        ).all()
    )
    if orphan_operation_ids:
        db.execute(
            delete(MetadataWritebackOperation).where(
                MetadataWritebackOperation.id.in_(orphan_operation_ids)
            )
        )
    cleaned = len(terminal_ids) + len(orphan_operation_ids)
    if cleaned:
        reconcile_queue_state(db)
    return cleaned


def queue_status(db: Session, *, capacity: int) -> dict[str, int | float]:
    pending = int(
        db.scalar(
            select(MetadataOpfQueueState.pending_targets).where(
                MetadataOpfQueueState.id == QUEUE_STATE_ID
            )
        )
        or 0
    )
    return {
        "pendingTargets": pending,
        "capacity": capacity,
        "utilization": pending / capacity if capacity else 0.0,
    }

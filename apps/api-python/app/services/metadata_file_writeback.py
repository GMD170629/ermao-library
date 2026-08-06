"""Recoverable worker boundary for metadata OPF sidecar save operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.system import record_system_event
from app.core.config import Settings, get_settings
from app.models.library import LibraryMediaVersion
from app.modules.metadata.infrastructure import file_writeback, writeback_queue

LOGGER = logging.getLogger(__name__)


def enqueue_metadata_writeback(
    db: Session,
    *,
    work_id: str,
    media_version_id: str,
    source: str,
    lookup_task_id: str | None = None,
    volume_id: str | None = None,
) -> str | None:
    result = writeback_queue.enqueue_writeback(
        db,
        work_id=work_id,
        media_version_id=media_version_id,
        source=source,
        lookup_task_id=lookup_task_id,
        volume_id=volume_id,
        max_pending_targets=get_settings().metadata_opf_queue_max_pending,
    )
    return result.operation_id


def schedule_work_metadata_writebacks(
    db: Session,
    *,
    work_id: str,
    source: str,
    lookup_task_id: str | None = None,
    media_version_id: str | None = None,
    volume_id: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, ...]:
    """Observe one committed intent and durably schedule its OPF side effects."""
    scheduled_work_ids = db.info.setdefault("metadata_opf_scheduled_work_ids", set())
    if isinstance(scheduled_work_ids, set):
        scheduled_work_ids.add(work_id)
    if not writeback_queue.write_metadata_to_files_enabled(db):
        return ()
    active_settings = settings or get_settings()
    media_version_ids = (
        [media_version_id]
        if media_version_id
        else list(
            db.scalars(
                select(LibraryMediaVersion.id)
                .where(LibraryMediaVersion.work_id == work_id)
                .order_by(LibraryMediaVersion.created_at.asc())
            ).all()
        )
    )
    operation_ids: list[str] = []
    queued_targets = 0
    dropped_targets = 0
    for current_media_version_id in media_version_ids:
        result = writeback_queue.enqueue_writeback(
            db,
            work_id=work_id,
            media_version_id=current_media_version_id,
            source=source,
            lookup_task_id=lookup_task_id,
            volume_id=volume_id,
            max_pending_targets=active_settings.metadata_opf_queue_max_pending,
        )
        if result.operation_id:
            operation_ids.append(result.operation_id)
            queued_targets += result.requested_targets
        elif result.outcome == "QUEUE_FULL":
            dropped_targets += result.requested_targets
    if dropped_targets:
        writeback_queue.discard_operations(db, tuple(operation_ids))
        dropped_targets += queued_targets
        operation_ids.clear()
        status = writeback_queue.queue_status(
            db, capacity=active_settings.metadata_opf_queue_max_pending
        )
        record_system_event(
            db,
            source="metadata",
            action="metadata.opf_queue_full",
            message="OPF 同步队列容量不足，本次同步任务已丢弃",
            level="warning",
            target_type="work",
            target_id=work_id,
            metadata={
                "droppedTargets": dropped_targets,
                "pendingTargets": status["pendingTargets"],
                "capacity": status["capacity"],
            },
        )
    return tuple(operation_ids)


def metadata_writeback_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    return writeback_queue.operation_view(db, operation_id)


def metadata_writeback_view_for_lookup_task(
    db: Session, lookup_task_id: str | None
) -> dict[str, Any] | None:
    return writeback_queue.operation_view_for_lookup_task(db, lookup_task_id)


def metadata_writeback_work_id(db: Session, operation_id: str) -> str | None:
    return writeback_queue.operation_work_id(db, operation_id)


def metadata_opf_queue_status(
    db: Session, settings: Settings
) -> dict[str, int | float]:
    return writeback_queue.queue_status(
        db, capacity=settings.metadata_opf_queue_max_pending
    )


def process_next_metadata_writeback(db: Session, settings: Settings) -> bool:
    target = writeback_queue.claim_next_target(db)
    if target is None:
        if writeback_queue.cleanup_terminal_history(db):
            db.commit()
            return True
        return False
    db.commit()
    target_id = str(target["id"])
    prepared_path = str(target.get("preparedPath") or "")
    try:
        if target["status"] != "PREPARED":
            prepared = file_writeback.prepare_writeback(
                str(target["sourcePath"]),
                dict(target["payload"]),
                settings.resolved_storage_root,
            )
            prepared_path = str(prepared.prepared_path)
            writeback_queue.mark_prepared(
                db,
                target_id,
                prepared_path=prepared_path,
                output_hash=prepared.output_hash,
                warning_code=prepared.warning_code,
            )
            db.commit()
            output_hash = prepared.output_hash
            written_fields = prepared.written_fields
            warning_code = prepared.warning_code
        else:
            output_hash = str(target.get("outputHash") or "")
            written_fields = tuple(
                str(item)
                for item in target.get("payload", {})
                if item not in {"sourceSize", "sourceMtimeMs", "coverPath"}
            )
            warning_code = (
                str(target.get("warningCode")) if target.get("warningCode") else None
            )
        output, published_size_bytes, published_mtime_ms = (
            file_writeback.publish_prepared(
                str(target["sourcePath"]), prepared_path, output_hash
            )
        )
        size_bytes: int | None = published_size_bytes
        mtime_ms: int | None = published_mtime_ms
        source = Path(str(target["sourcePath"])).expanduser().resolve()
        if output.resolve() != source:
            size_bytes = None
            mtime_ms = None
        writeback_queue.complete_target(
            db,
            target_id,
            written_fields=written_fields,
            size_bytes=size_bytes,
            mtime_ms=mtime_ms,
            warning_code=warning_code,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - contains one recoverable worker target.
        db.rollback()
        if prepared_path:
            Path(prepared_path).unlink(missing_ok=True)
        LOGGER.warning(
            "metadata OPF sidecar save failed target=%s operation=%s: %s",
            target_id,
            target.get("operationId"),
            exc,
        )
        record_system_event(
            db,
            source="metadata",
            action="metadata.opf_write_failed",
            message="旁车 OPF 保存失败，任务不会重试",
            level="warning",
            target_type="metadataOpfTarget",
            target_id=target_id,
            metadata={
                "operationId": str(target.get("operationId") or ""),
                "format": str(target.get("format") or ""),
                "errorType": type(exc).__name__,
            },
        )
        writeback_queue.fail_target(
            db,
            target_id,
            code="FILE_METADATA_WRITEBACK_FAILED",
            summary=str(exc),
        )
        db.commit()
    return True


def recover_interrupted_metadata_writebacks(db: Session) -> int:
    writeback_queue.cleanup_terminal_history(db)
    recovered = writeback_queue.recover_interrupted_targets(db)
    db.commit()
    return recovered

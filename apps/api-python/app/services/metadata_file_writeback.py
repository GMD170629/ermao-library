"""Recoverable worker boundary for metadata OPF sidecar save operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
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
) -> str:
    return writeback_queue.enqueue_writeback(
        db,
        work_id=work_id,
        media_version_id=media_version_id,
        source=source,
        lookup_task_id=lookup_task_id,
        volume_id=volume_id,
    )


def metadata_writeback_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    return writeback_queue.operation_view(db, operation_id)


def metadata_writeback_view_for_lookup_task(
    db: Session, lookup_task_id: str | None
) -> dict[str, Any] | None:
    return writeback_queue.operation_view_for_lookup_task(db, lookup_task_id)


def metadata_writeback_work_id(db: Session, operation_id: str) -> str | None:
    return writeback_queue.operation_work_id(db, operation_id)


def process_next_metadata_writeback(db: Session, settings: Settings) -> bool:
    target = writeback_queue.claim_next_target(db)
    if target is None:
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
        writeback_queue.fail_target(
            db,
            target_id,
            code="FILE_METADATA_WRITEBACK_FAILED",
            summary=str(exc),
        )
        db.commit()
    return True


def recover_interrupted_metadata_writebacks(db: Session) -> int:
    recovered = writeback_queue.recover_interrupted_targets(db)
    db.commit()
    return recovered

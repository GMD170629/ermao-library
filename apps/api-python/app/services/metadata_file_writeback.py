"""Recoverable worker boundary for metadata OPF sidecar save operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.bootstrap.system import prepare_system_event, write_prepared_system_events
from app.core.config import Settings, get_settings
from app.models.common import db_timestamp
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.application.writeback import (
    MetadataWritebackProjection,
    PreparedWritebackIntent,
    prepare_metadata_writeback_intents,
)
from app.modules.metadata.infrastructure import file_writeback, writeback_queue

LOGGER = logging.getLogger(__name__)


def load_metadata_writeback_projection(
    db: Session,
    *,
    work_id: str,
    media_version_id: str | None = None,
    volume_id: str | None = None,
) -> MetadataWritebackProjection:
    return writeback_queue.load_metadata_writeback_projection(
        db,
        work_id=work_id,
        media_version_id=media_version_id,
        volume_id=volume_id,
    )


def persist_metadata_writeback_intents(
    db: Session,
    intents: tuple[PreparedWritebackIntent, ...],
) -> tuple[str, ...]:
    return writeback_queue.enqueue_prepared_writeback_intents(db, intents)


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
    """Prepare immutable projections, then persist all queue intents together."""

    if not writeback_queue.write_metadata_to_files_enabled(db):
        return ()
    del settings
    projection = writeback_queue.load_metadata_writeback_projection(
        db,
        work_id=work_id,
        media_version_id=media_version_id,
        volume_id=volume_id,
    )
    intents = prepare_metadata_writeback_intents(
        projection,
        source=source,
        lookup_task_id=lookup_task_id,
        volume_id=volume_id,
    )
    return writeback_queue.enqueue_prepared_writeback_intents(db, intents)


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


def _claim_preparation_uow(db: Session, owner_id: str) -> dict[str, Any] | None:
    now = db_timestamp()
    with MetadataWriteTransaction(db):
        preparation = writeback_queue.claim_next_preparation(
            db, owner_id=owner_id, now=now
        )
    return preparation


def _finalize_preparation_uow(
    db: Session,
    preparation: dict[str, Any],
    owner_id: str,
    targets: tuple[writeback_queue.PreparedTargetInsert, ...],
    capacity: int,
) -> None:
    prepared_write = writeback_queue.prepare_preparation_finalization(
        preparation_id=str(preparation["id"]),
        operation_id=str(preparation["operationId"]),
        owner_id=owner_id,
        targets=targets,
        max_pending_targets=capacity,
        now=db_timestamp(),
    )
    with MetadataWriteTransaction(db):
        writeback_queue.finalize_preparation(db, prepared_write)


def _claim_target_uow(db: Session, owner_id: str) -> dict[str, Any] | None:
    now = db_timestamp()
    with MetadataWriteTransaction(db):
        target = writeback_queue.claim_next_target(db, owner_id=owner_id, now=now)
    return writeback_queue.decode_claimed_target(target) if target is not None else None


def _mark_target_prepared_uow(
    db: Session,
    *,
    target_id: str,
    owner_id: str,
    prepared_path: str,
    output_hash: str,
    warning_code: str | None,
) -> None:
    now = db_timestamp()
    with MetadataWriteTransaction(db):
        updated = writeback_queue.mark_prepared(
            db,
            target_id,
            owner_id=owner_id,
            prepared_path=prepared_path,
            output_hash=output_hash,
            warning_code=warning_code,
            now=now,
        )
        if not updated:
            raise RuntimeError("metadata writeback target lease was lost")


def _complete_target_uow(
    db: Session,
    *,
    target_id: str,
    owner_id: str,
    written_fields: tuple[str, ...],
    size_bytes: int | None,
    mtime_ms: int | None,
    warning_code: str | None,
) -> None:
    now = db_timestamp()
    with MetadataWriteTransaction(db):
        completed = writeback_queue.complete_target(
            db,
            target_id,
            owner_id=owner_id,
            written_fields=written_fields,
            size_bytes=size_bytes,
            mtime_ms=mtime_ms,
            warning_code=warning_code,
            now=now,
        )
        if not completed:
            raise RuntimeError("metadata writeback target lease was lost")


def _fail_target_uow(
    db: Session,
    *,
    target: dict[str, Any],
    owner_id: str,
    summary: str,
    error_type: str,
) -> None:
    target_id = str(target["id"])
    event_metadata = {
        "operationId": str(target.get("operationId") or ""),
        "format": str(target.get("format") or ""),
        "errorType": error_type,
    }
    event = prepare_system_event(
        source="metadata",
        action="metadata.opf_write_failed",
        message="旁车 OPF 保存失败，任务不会重试",
        level="warning",
        target_type="metadataOpfTarget",
        target_id=target_id,
        metadata=event_metadata,
    )
    now = db_timestamp()
    with MetadataWriteTransaction(db):
        write_prepared_system_events(db, [event])
        writeback_queue.fail_target(
            db,
            target_id,
            owner_id=owner_id,
            code="FILE_METADATA_WRITEBACK_FAILED",
            summary=summary,
            now=now,
        )


def _cleanup_orphan_prepared_files(
    projection: writeback_queue.WritebackCleanupProjection,
    settings: Settings,
) -> int:
    directories: list[Path] = [settings.resolved_storage_root]
    for source_value in projection.source_paths:
        source = Path(source_value).expanduser()
        directories.append(source if source.is_dir() else source.parent)
    protected = frozenset(
        Path(value).expanduser() for value in projection.protected_prepared_paths
    )
    return file_writeback.cleanup_orphan_prepared_files(
        tuple(directories),
        protected_paths=protected,
    )


def _cleanup_terminal_history_uow(
    db: Session,
) -> tuple[bool, writeback_queue.WritebackCleanupProjection]:
    cleanup_projection = writeback_queue.load_writeback_cleanup_projection(db)
    prepared_cleanup = writeback_queue.prepare_terminal_history_cleanup(db)
    db.close()
    with MetadataWriteTransaction(db):
        cleaned = bool(
            writeback_queue.write_prepared_terminal_history_cleanup(
                db, prepared_cleanup
            )
        )
    return cleaned, cleanup_projection


def process_next_metadata_writeback(
    db: Session,
    settings: Settings,
    *,
    owner_id: str = "metadata-writeback-compat",
    prefer_preparation: bool = True,
) -> bool:
    if prefer_preparation:
        preparation = _claim_preparation_uow(db, owner_id)
        if preparation is not None:
            targets = writeback_queue.prepare_targets_from_snapshot(preparation)
            _finalize_preparation_uow(
                db,
                preparation,
                owner_id,
                targets,
                settings.metadata_opf_queue_max_pending,
            )
            return True
    target = _claim_target_uow(db, owner_id)
    if target is None and not prefer_preparation:
        preparation = _claim_preparation_uow(db, owner_id)
        if preparation is not None:
            targets = writeback_queue.prepare_targets_from_snapshot(preparation)
            _finalize_preparation_uow(
                db,
                preparation,
                owner_id,
                targets,
                settings.metadata_opf_queue_max_pending,
            )
            return True
    if target is None:
        cleaned, cleanup_projection = _cleanup_terminal_history_uow(db)
        _cleanup_orphan_prepared_files(cleanup_projection, settings)
        return cleaned
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
            _mark_target_prepared_uow(
                db,
                target_id=target_id,
                owner_id=owner_id,
                prepared_path=prepared_path,
                output_hash=prepared.output_hash,
                warning_code=prepared.warning_code,
            )
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
        _complete_target_uow(
            db,
            target_id=target_id,
            owner_id=owner_id,
            written_fields=written_fields,
            size_bytes=size_bytes,
            mtime_ms=mtime_ms,
            warning_code=warning_code,
        )
    except Exception as exc:  # noqa: BLE001 - contains one recoverable worker target.
        if prepared_path:
            Path(prepared_path).unlink(missing_ok=True)
        LOGGER.warning(
            "metadata OPF sidecar save failed target=%s operation=%s: %s",
            target_id,
            target.get("operationId"),
            exc,
        )
        _fail_target_uow(
            db,
            target=target,
            owner_id=owner_id,
            summary=str(exc),
            error_type=type(exc).__name__,
        )
    return True


def recover_interrupted_metadata_writebacks(
    db: Session,
    settings: Settings | None = None,
) -> int:
    cleanup_projection = writeback_queue.load_writeback_cleanup_projection(db)
    prepared_cleanup = writeback_queue.prepare_terminal_history_cleanup(db)
    now = db_timestamp()
    db.close()
    with MetadataWriteTransaction(db):
        writeback_queue.write_prepared_terminal_history_cleanup(db, prepared_cleanup)
        recovered = writeback_queue.recover_interrupted_targets(db, now=now)
    if settings is not None:
        _cleanup_orphan_prepared_files(cleanup_projection, settings)
    return recovered

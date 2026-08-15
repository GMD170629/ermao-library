"""ORM persistence for recoverable metadata file writeback operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import case, delete, func, insert, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
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
    MetadataWritebackPreparation,
    MetadataWritebackTarget,
    OrganizePolicy,
)
from app.modules.metadata.application.writeback import (
    NULL_SOURCE_REVISION,
    MetadataWritebackFileProjection,
    MetadataWritebackImportProjection,
    MetadataWritebackProjection,
    MetadataWritebackVolumeProjection,
    PreparedWritebackIntent,
    prepare_metadata_writeback_intents,
)

DEFAULT_MAX_PENDING_TARGETS = 50_000
QUEUE_STATE_ID = "default"
WRITEBACK_LEASE_SECONDS = 60
PREPARATION_DEFER_SECONDS = 5
WRITEBACK_CLEANUP_PATH_LIMIT = 512


@dataclass(frozen=True, slots=True)
class EnqueueWritebackResult:
    operation_id: str | None
    requested_targets: int
    outcome: str


@dataclass(frozen=True, slots=True)
class PreparedTargetInsert:
    id: str
    operation_id: str
    library_file_id: str | None
    target_key: str
    source_path: str
    format: str
    payload_json: str


@dataclass(frozen=True, slots=True)
class WritebackCleanupProjection:
    source_paths: tuple[str, ...]
    protected_prepared_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedTerminalHistoryCleanup:
    statements: tuple[Executable, ...]
    cleaned: int


@dataclass(frozen=True, slots=True)
class PreparedPreparationFinalization:
    owned_query: Executable
    no_target_statements: tuple[Executable, ...]
    reserve_statement: Executable | None
    deferred_statements: tuple[Executable, ...]
    expanded_statements: tuple[Executable, ...]
    delete_preparation_statement: Executable | None
    finish_statements: tuple[Executable, ...]


def load_writeback_cleanup_projection(
    db: Session,
    *,
    limit: int = WRITEBACK_CLEANUP_PATH_LIMIT,
) -> WritebackCleanupProjection:
    """Load a bounded path projection for transaction-external orphan cleanup."""

    bounded = min(max(limit, 1), WRITEBACK_CLEANUP_PATH_LIMIT)
    target_sources = tuple(
        str(value)
        for value in db.scalars(
            select(MetadataWritebackTarget.source_path)
            .where(
                MetadataWritebackTarget.status.in_(("PENDING", "RUNNING", "PREPARED"))
            )
            .order_by(MetadataWritebackTarget.updated_at.desc())
            .limit(bounded)
        ).all()
        if value
    )
    remaining = max(0, bounded - len(target_sources))
    library_sources = (
        tuple(
            str(value)
            for value in db.scalars(
                select(LibraryFile.path)
                .where(LibraryFile.path.is_not(None))
                .order_by(LibraryFile.updated_at.desc())
                .limit(remaining)
            ).all()
            if value
        )
        if remaining
        else ()
    )
    protected = tuple(
        str(value)
        for value in db.scalars(
            select(MetadataWritebackTarget.prepared_path)
            .where(
                MetadataWritebackTarget.prepared_path.is_not(None),
                MetadataWritebackTarget.status.in_(("RUNNING", "PREPARED")),
            )
            .order_by(MetadataWritebackTarget.updated_at.desc())
            .limit(bounded)
        ).all()
        if value
    )
    return WritebackCleanupProjection(
        source_paths=target_sources + library_sources,
        protected_prepared_paths=protected,
    )


def write_metadata_to_files_enabled(db: Session) -> bool:
    value = db.scalar(
        select(OrganizePolicy.write_metadata_to_files).where(
            OrganizePolicy.id == "default"
        )
    )
    return bool(value)


def load_metadata_writeback_projection(
    db: Session,
    *,
    work_id: str,
    media_version_id: str | None = None,
    volume_id: str | None = None,
) -> MetadataWritebackProjection:
    """Load an explicit projection; callers prepare intents before their write UoW."""

    work = db.scalar(select(LibraryWork).where(LibraryWork.id == work_id))
    if work is None:
        raise ValueError("作品不存在")
    media_query = select(LibraryMediaVersion.id).where(
        LibraryMediaVersion.work_id == work_id
    )
    if media_version_id is not None:
        media_query = media_query.where(LibraryMediaVersion.id == media_version_id)
    media_ids = tuple(
        db.scalars(media_query.order_by(LibraryMediaVersion.created_at.asc())).all()
    )
    if media_version_id is not None and not media_ids:
        raise ValueError("媒介版本不存在")
    volume_query = select(LibraryVolume).where(
        LibraryVolume.media_version_id.in_(media_ids),
        LibraryVolume.hidden.is_(False),
    )
    if volume_id is not None:
        volume_query = volume_query.where(LibraryVolume.id == volume_id)
    volume_rows = tuple(
        db.scalars(
            volume_query.order_by(
                LibraryVolume.media_version_id.asc(),
                LibraryVolume.sort_order.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
    )
    volume_ids = tuple(volume.id for volume in volume_rows)
    file_rows = (
        tuple(
            db.scalars(
                select(LibraryFile)
                .where(LibraryFile.volume_id.in_(volume_ids))
                .order_by(
                    LibraryFile.volume_id.asc(),
                    LibraryFile.sort_order.asc(),
                    LibraryFile.id.asc(),
                )
            ).all()
        )
        if volume_ids
        else ()
    )
    import_rows = (
        tuple(
            db.execute(
                select(ImportTask.id, ImportTask.volume_id, ImportTask.source_path)
                .where(
                    ImportTask.volume_id.in_(volume_ids),
                    ImportTask.status == "COMPLETED",
                )
                .order_by(ImportTask.created_at.asc(), ImportTask.id.asc())
            ).all()
        )
        if volume_ids
        else ()
    )
    import_ids = tuple(str(row.id) for row in import_rows)
    asset_rows = (
        tuple(
            db.execute(
                select(ImportAsset.import_task_id, ImportAsset.source_path)
                .where(ImportAsset.import_task_id.in_(import_ids))
                .order_by(
                    ImportAsset.import_task_id.asc(),
                    ImportAsset.sort_order.asc(),
                    ImportAsset.id.asc(),
                )
            ).all()
        )
        if import_ids
        else ()
    )
    assets_by_import: dict[str, list[str]] = {}
    for asset in asset_rows:
        assets_by_import.setdefault(str(asset.import_task_id), []).append(
            str(asset.source_path)
        )
    return MetadataWritebackProjection(
        work_id=work.id,
        title=work.title,
        author=work.author,
        description=work.description,
        tags_json=work.tags,
        series_name=work.series_name,
        series_index=work.series_index,
        cover_path=work.cover_path,
        source_revision=work.updated_at or NULL_SOURCE_REVISION,
        media_version_ids=media_ids,
        volumes=tuple(
            MetadataWritebackVolumeProjection(
                id=volume.id,
                media_version_id=volume.media_version_id,
                title=volume.title,
                description=volume.description,
                volume_index=volume.volume_index,
                narrator=volume.narrator,
                abridged=volume.abridged,
                language=volume.language,
                publisher=volume.publisher,
                published_at=volume.published_at,
                identifier=volume.identifier,
                isbn=volume.isbn,
                cover_path=volume.cover_path,
            )
            for volume in volume_rows
        ),
        files=tuple(
            MetadataWritebackFileProjection(
                id=file.id,
                volume_id=file.volume_id,
                path=file.path,
                size_bytes=file.size_bytes,
                mtime_ms=file.mtime_ms,
            )
            for file in file_rows
        ),
        imports=tuple(
            MetadataWritebackImportProjection(
                volume_id=str(row.volume_id),
                source_path=str(row.source_path),
                asset_paths=tuple(assets_by_import.get(str(row.id), ())),
            )
            for row in import_rows
        ),
    )


def enqueue_prepared_writeback_intents(
    db: Session,
    intents: tuple[PreparedWritebackIntent, ...],
    *,
    max_pending_preparations: int = DEFAULT_MAX_PENDING_TARGETS,
) -> tuple[str, ...]:
    """Persist prepared intents with one short set-based write boundary."""

    if not intents:
        return ()
    now = db_timestamp()
    keys = tuple(intent.idempotency_key for intent in intents)
    existing_keys: set[str] = set()
    for key_chunk in sqlite_parameter_chunks(keys, parameters_per_row=1):
        existing_keys.update(
            str(key)
            for key in db.scalars(
                select(MetadataWritebackPreparation.idempotency_key).where(
                    MetadataWritebackPreparation.idempotency_key.in_(key_chunk)
                )
            ).all()
        )
    pending = tuple(
        intent for intent in intents if intent.idempotency_key not in existing_keys
    )
    operation_rows = tuple(
        {
            "id": intent.operation_id,
            "work_id": intent.work_id,
            "media_version_id": intent.media_version_id,
            "lookup_task_id": intent.lookup_task_id,
            "source": intent.source,
            "status": "PENDING",
            "total_targets": 0,
            "completed_targets": 0,
            "warning_targets": 0,
            "created_at": now,
            "updated_at": now,
        }
        for intent in pending
    )
    preparation_rows = tuple(
        {
            "id": intent.preparation_id,
            "operation_id": intent.operation_id,
            "work_id": intent.work_id,
            "media_version_id": intent.media_version_id,
            "volume_id": intent.volume_id,
            "lookup_task_id": intent.lookup_task_id,
            "source": intent.source,
            "idempotency_key": intent.idempotency_key,
            "source_revision": intent.source_revision,
            "snapshot_json": intent.snapshot_json,
            "status": "PENDING",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        }
        for intent in pending
    )
    db.execute(
        sqlite_insert(MetadataOpfQueueState)
        .values(
            id=QUEUE_STATE_ID,
            pending_targets=0,
            pending_preparations=0,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[MetadataOpfQueueState.id])
    )
    if pending:
        reserved = db.execute(
            update(MetadataOpfQueueState)
            .where(
                MetadataOpfQueueState.id == QUEUE_STATE_ID,
                MetadataOpfQueueState.pending_preparations
                <= max_pending_preparations - len(pending),
            )
            .values(
                pending_preparations=(
                    MetadataOpfQueueState.pending_preparations + len(pending)
                ),
                updated_at=now,
            )
        )
        if not reserved.rowcount:
            return tuple(
                intent.operation_id
                for intent in intents
                if intent.idempotency_key in existing_keys
            )
        for chunk in sqlite_parameter_chunks(operation_rows, parameters_per_row=11):
            db.execute(
                sqlite_insert(MetadataWritebackOperation)
                .values(list(chunk))
                .on_conflict_do_nothing(index_elements=[MetadataWritebackOperation.id])
            )
        inserted_preparations = 0
        for chunk in sqlite_parameter_chunks(preparation_rows, parameters_per_row=14):
            result = db.execute(
                sqlite_insert(MetadataWritebackPreparation)
                .values(list(chunk))
                .on_conflict_do_nothing(
                    index_elements=[MetadataWritebackPreparation.idempotency_key]
                )
            )
            inserted_preparations += int(result.rowcount or 0)
        duplicate_reservations = len(pending) - inserted_preparations
        if duplicate_reservations:
            db.execute(
                update(MetadataOpfQueueState)
                .where(MetadataOpfQueueState.id == QUEUE_STATE_ID)
                .values(
                    pending_preparations=func.max(
                        0,
                        MetadataOpfQueueState.pending_preparations
                        - duplicate_reservations,
                    ),
                    updated_at=now,
                )
            )
    return tuple(intent.operation_id for intent in intents)


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
    del max_pending_targets  # Capacity is checked when preparation becomes targets.
    projection = load_metadata_writeback_projection(
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
    operation_ids = enqueue_prepared_writeback_intents(db, intents)
    if not operation_ids:
        return EnqueueWritebackResult(None, 0, "NO_TARGETS")
    return EnqueueWritebackResult(operation_ids[0], 0, "QUEUED")


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


def claim_next_preparation(
    db: Session,
    *,
    owner_id: str,
    now: datetime,
    lease_seconds: int = WRITEBACK_LEASE_SECONDS,
) -> dict[str, Any] | None:
    candidate_id = (
        select(MetadataWritebackPreparation.id)
        .where(
            or_(
                (
                    (MetadataWritebackPreparation.status == "PENDING")
                    & or_(
                        MetadataWritebackPreparation.next_attempt_at.is_(None),
                        MetadataWritebackPreparation.next_attempt_at <= now,
                    )
                ),
                (
                    (MetadataWritebackPreparation.status == "RUNNING")
                    & (MetadataWritebackPreparation.lease_expires_at <= now)
                ),
            )
        )
        .order_by(
            MetadataWritebackPreparation.created_at.asc(),
            MetadataWritebackPreparation.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    row = db.execute(
        update(MetadataWritebackPreparation)
        .where(MetadataWritebackPreparation.id == candidate_id)
        .values(
            status="RUNNING",
            attempts=MetadataWritebackPreparation.attempts + 1,
            lease_owner_id=owner_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .returning(
            MetadataWritebackPreparation.id,
            MetadataWritebackPreparation.operation_id,
            MetadataWritebackPreparation.work_id,
            MetadataWritebackPreparation.source_revision,
            MetadataWritebackPreparation.snapshot_json,
            MetadataWritebackPreparation.attempts,
        )
    ).one_or_none()
    if row is None:
        return None
    if row.operation_id:
        db.execute(
            update(MetadataWritebackOperation)
            .where(MetadataWritebackOperation.id == row.operation_id)
            .values(status="RUNNING", updated_at=now)
        )
    return {
        "id": row.id,
        "operationId": row.operation_id,
        "workId": row.work_id,
        "sourceRevision": row.source_revision,
        "snapshotJson": row.snapshot_json,
        "attempts": row.attempts,
        "leaseOwnerId": owner_id,
    }


def prepare_targets_from_snapshot(
    preparation: dict[str, Any],
) -> tuple[PreparedTargetInsert, ...]:
    """Perform path resolution and filesystem inspection without a transaction."""

    parsed = json.loads(str(preparation["snapshotJson"]))
    volumes = parsed.get("volumes") if isinstance(parsed, dict) else None
    if not isinstance(volumes, list):
        # This is an invalid persisted business snapshot, not a caller type error.
        raise ValueError("invalid writeback preparation snapshot")  # noqa: TRY004
    operation_id = str(preparation["operationId"])
    targets: list[PreparedTargetInsert] = []
    seen: set[Path] = set()
    for raw_volume in volumes:
        if not isinstance(raw_volume, dict):
            continue
        raw_payload = raw_volume.get("payload")
        payload_base = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        raw_files = raw_volume.get("files")
        file_values = raw_files if isinstance(raw_files, list) else []
        files_by_path: dict[Path, dict[str, object]] = {}
        for raw_file in file_values:
            if not isinstance(raw_file, dict) or not raw_file.get("path"):
                continue
            files_by_path[Path(str(raw_file["path"])).expanduser().resolve()] = raw_file
        sources: list[str] = []
        raw_tasks = raw_volume.get("importTasks")
        tasks = raw_tasks if isinstance(raw_tasks, list) else []
        for raw_task in tasks:
            if not isinstance(raw_task, dict) or not raw_task.get("sourcePath"):
                continue
            task_path = Path(str(raw_task["sourcePath"])).expanduser()
            assets = raw_task.get("assetPaths")
            if task_path.is_dir() and isinstance(assets, list):
                sources.extend(str(path) for path in assets)
            else:
                sources.append(str(task_path))
        if not sources:
            sources = [str(path) for path in files_by_path]
        for source_value in sources:
            target_path = Path(source_value).expanduser().resolve()
            if target_path in seen:
                continue
            seen.add(target_path)
            matching_file = files_by_path.get(target_path)
            try:
                target_stat = target_path.stat() if target_path.is_file() else None
            except OSError:
                target_stat = None
            payload = {
                **payload_base,
                "sourceSize": (
                    matching_file.get("size")
                    if matching_file is not None
                    else target_stat.st_size
                    if target_stat
                    else None
                ),
                "sourceMtimeMs": (
                    matching_file.get("mtimeMs")
                    if matching_file is not None
                    else int(target_stat.st_mtime * 1000)
                    if target_stat
                    else None
                ),
            }
            targets.append(
                PreparedTargetInsert(
                    id=f"metadata_writeback_target_{uuid4().hex}",
                    operation_id=operation_id,
                    library_file_id=(
                        str(matching_file["id"])
                        if matching_file is not None and matching_file.get("id")
                        else None
                    ),
                    target_key=hashlib.sha256(
                        str(target_path).encode("utf-8")
                    ).hexdigest(),
                    source_path=str(target_path),
                    format=(
                        target_path.suffix.removeprefix(".") or "DIRECTORY"
                    ).upper(),
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            )
    return tuple(targets)


def prepare_preparation_finalization(
    *,
    preparation_id: str,
    operation_id: str,
    owner_id: str,
    targets: tuple[PreparedTargetInsert, ...],
    max_pending_targets: int,
    now: datetime,
) -> PreparedPreparationFinalization:
    target_rows = tuple(
        {
            "id": target.id,
            "operation_id": target.operation_id,
            "library_file_id": target.library_file_id,
            "target_key": target.target_key,
            "source_path": target.source_path,
            "format": target.format,
            "payload_json": target.payload_json,
            "status": "PENDING",
            "attempts": 0,
            "written_fields_json": "[]",
            "created_at": now,
            "updated_at": now,
        }
        for target in targets
    )
    owned_query = select(MetadataWritebackPreparation.id).where(
        MetadataWritebackPreparation.id == preparation_id,
        MetadataWritebackPreparation.operation_id == operation_id,
        MetadataWritebackPreparation.status == "RUNNING",
        MetadataWritebackPreparation.lease_owner_id == owner_id,
    )
    no_target_statements = (
        delete(MetadataWritebackPreparation).where(
            MetadataWritebackPreparation.id == preparation_id,
            MetadataWritebackPreparation.lease_owner_id == owner_id,
        ),
        delete(MetadataWritebackOperation).where(
            MetadataWritebackOperation.id == operation_id
        ),
        update(MetadataOpfQueueState)
        .where(MetadataOpfQueueState.id == QUEUE_STATE_ID)
        .values(
            pending_preparations=func.max(
                0, MetadataOpfQueueState.pending_preparations - 1
            ),
            updated_at=now,
        ),
    )
    reserve_statement = (
        update(MetadataOpfQueueState)
        .where(
            MetadataOpfQueueState.id == QUEUE_STATE_ID,
            MetadataOpfQueueState.pending_targets <= max_pending_targets - len(targets),
        )
        .values(
            pending_targets=MetadataOpfQueueState.pending_targets + len(targets),
            updated_at=now,
        )
        if targets
        else None
    )
    deferred_statements = (
        update(MetadataWritebackPreparation)
            .where(
                MetadataWritebackPreparation.id == preparation_id,
                MetadataWritebackPreparation.status == "RUNNING",
                MetadataWritebackPreparation.lease_owner_id == owner_id,
            )
            .values(
                status="PENDING",
                next_attempt_at=now + timedelta(seconds=PREPARATION_DEFER_SECONDS),
                lease_owner_id=None,
                lease_expires_at=None,
                error_code="QUEUE_CAPACITY_DEFERRED",
                error_summary=None,
                updated_at=now,
            ),
        update(MetadataWritebackOperation)
            .where(MetadataWritebackOperation.id == operation_id)
            .values(status="PENDING", updated_at=now),
    )
    expanded_statements = tuple(
        insert(MetadataWritebackTarget).values(list(chunk))
        for chunk in sqlite_parameter_chunks(target_rows, parameters_per_row=12)
    ) + (
        update(MetadataWritebackOperation)
        .where(MetadataWritebackOperation.id == operation_id)
        .values(status="PENDING", total_targets=len(targets), updated_at=now),
    )
    delete_preparation_statement = (
        delete(MetadataWritebackPreparation).where(
            MetadataWritebackPreparation.id == preparation_id,
            MetadataWritebackPreparation.status == "RUNNING",
            MetadataWritebackPreparation.lease_owner_id == owner_id,
        )
        if targets
        else None
    )
    finish_statements = (
        update(MetadataOpfQueueState)
        .where(MetadataOpfQueueState.id == QUEUE_STATE_ID)
        .values(
            pending_preparations=func.max(
                0, MetadataOpfQueueState.pending_preparations - 1
            ),
            updated_at=now,
        ),
    )
    return PreparedPreparationFinalization(
        owned_query=owned_query,
        no_target_statements=no_target_statements,
        reserve_statement=reserve_statement,
        deferred_statements=deferred_statements,
        expanded_statements=expanded_statements,
        delete_preparation_statement=delete_preparation_statement,
        finish_statements=finish_statements,
    )


def finalize_preparation(
    db: Session,
    prepared: PreparedPreparationFinalization,
) -> str:
    """CAS-admit all targets, or defer without losing the durable intent."""

    if db.scalar(prepared.owned_query) is None:
        return "LEASE_LOST"
    if prepared.reserve_statement is None:
        for statement in prepared.no_target_statements:
            db.execute(statement)
        return "NO_TARGETS"
    reserved = db.execute(prepared.reserve_statement)
    if not reserved.rowcount:
        for statement in prepared.deferred_statements:
            db.execute(statement)
        return "DEFERRED"
    for statement in prepared.expanded_statements:
        db.execute(statement)
    if prepared.delete_preparation_statement is None:
        raise RuntimeError("writeback preparation delete statement missing")
    deleted = db.execute(prepared.delete_preparation_statement)
    if not deleted.rowcount:
        raise RuntimeError("writeback preparation lease was lost")
    for statement in prepared.finish_statements:
        db.execute(statement)
    return "EXPANDED"


def claim_next_target(
    db: Session,
    *,
    owner_id: str,
    now: datetime,
    lease_seconds: int = WRITEBACK_LEASE_SECONDS,
) -> dict[str, Any] | None:
    candidate_id = (
        select(MetadataWritebackTarget.id)
        .where(
            or_(
                (
                    (MetadataWritebackTarget.status == "PREPARED")
                    & or_(
                        MetadataWritebackTarget.lease_owner_id == owner_id,
                        MetadataWritebackTarget.lease_expires_at <= now,
                    )
                ),
                (
                    (MetadataWritebackTarget.status == "PENDING")
                    & or_(
                        MetadataWritebackTarget.next_attempt_at.is_(None),
                        MetadataWritebackTarget.next_attempt_at <= now,
                    )
                ),
                (
                    (MetadataWritebackTarget.status == "RUNNING")
                    & (MetadataWritebackTarget.lease_expires_at <= now)
                ),
            )
        )
        .order_by(
            MetadataWritebackTarget.created_at.asc(),
            MetadataWritebackTarget.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    row = db.execute(
        update(MetadataWritebackTarget)
        .where(MetadataWritebackTarget.id == candidate_id)
        .values(
            status=case(
                (MetadataWritebackTarget.status == "PENDING", "RUNNING"),
                else_=MetadataWritebackTarget.status,
            ),
            attempts=case(
                (
                    MetadataWritebackTarget.status.in_(("PENDING", "RUNNING")),
                    MetadataWritebackTarget.attempts + 1,
                ),
                else_=MetadataWritebackTarget.attempts,
            ),
            lease_owner_id=owner_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .returning(
            MetadataWritebackTarget.id,
            MetadataWritebackTarget.operation_id,
            MetadataWritebackTarget.library_file_id,
            MetadataWritebackTarget.source_path,
            MetadataWritebackTarget.format,
            MetadataWritebackTarget.payload_json,
            MetadataWritebackTarget.status,
            MetadataWritebackTarget.attempts,
            MetadataWritebackTarget.prepared_path,
            MetadataWritebackTarget.warning_code,
        )
    ).one_or_none()
    if row is None:
        return None
    db.execute(
        update(MetadataWritebackOperation)
        .where(MetadataWritebackOperation.id == row.operation_id)
        .values(status="RUNNING", updated_at=now)
    )
    return {
        "id": row.id,
        "operationId": row.operation_id,
        "libraryFileId": row.library_file_id,
        "sourcePath": row.source_path,
        "format": row.format,
        "payloadJson": row.payload_json,
        "status": row.status,
        "attempts": row.attempts,
        "preparedPath": row.prepared_path,
        "warningCode": row.warning_code,
        "leaseOwnerId": owner_id,
    }


def decode_claimed_target(target: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(str(target.get("payloadJson") or "{}"))
    return {
        key: value for key, value in target.items() if key != "payloadJson"
    } | {"payload": payload if isinstance(payload, dict) else {}}


def recover_interrupted_targets(db: Session, *, now: datetime) -> int:
    recovered_count = int(
        db.scalar(
            select(func.count()).where(
                MetadataWritebackTarget.status == "RUNNING",
                MetadataWritebackTarget.lease_expires_at <= now,
            )
        )
        or 0
    )
    db.execute(
        update(MetadataWritebackTarget)
        .where(
            MetadataWritebackTarget.status == "RUNNING",
            MetadataWritebackTarget.lease_expires_at <= now,
        )
        .values(
            status="PENDING",
            next_attempt_at=None,
            lease_owner_id=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.execute(
        update(MetadataWritebackOperation)
        .where(
            MetadataWritebackOperation.status == "RUNNING",
            MetadataWritebackOperation.id.in_(
                select(MetadataWritebackTarget.operation_id).where(
                    MetadataWritebackTarget.status == "PENDING"
                )
            ),
        )
        .values(status="PENDING", updated_at=now)
    )
    reconcile_queue_state(db, now=now)
    return recovered_count


def mark_prepared(
    db: Session,
    target_id: str,
    *,
    owner_id: str,
    prepared_path: str,
    warning_code: str | None,
    now: datetime,
) -> bool:
    result = db.execute(
        update(MetadataWritebackTarget)
        .where(
            MetadataWritebackTarget.id == target_id,
            MetadataWritebackTarget.status == "RUNNING",
            MetadataWritebackTarget.lease_owner_id == owner_id,
        )
        .values(
            status="PREPARED",
            prepared_path=prepared_path,
            warning_code=warning_code,
            lease_expires_at=now + timedelta(seconds=WRITEBACK_LEASE_SECONDS),
            updated_at=now,
        )
    )
    return bool(result.rowcount)


def _release_target(
    db: Session,
    *,
    target_id: str,
    operation_id: str,
    owner_id: str,
    now: datetime,
) -> bool:
    result = db.execute(
        delete(MetadataWritebackTarget).where(
            MetadataWritebackTarget.id == target_id,
            MetadataWritebackTarget.lease_owner_id == owner_id,
        )
    )
    if not result.rowcount:
        return False
    db.execute(
        update(MetadataOpfQueueState)
        .where(
            MetadataOpfQueueState.id == QUEUE_STATE_ID,
            MetadataOpfQueueState.pending_targets > 0,
        )
        .values(
            pending_targets=MetadataOpfQueueState.pending_targets - 1,
            updated_at=now,
        )
    )
    db.flush()
    remaining = db.scalar(
        select(func.count()).where(MetadataWritebackTarget.operation_id == operation_id)
    )
    if not remaining:
        db.execute(
            delete(MetadataWritebackOperation).where(
                MetadataWritebackOperation.id == operation_id
            )
        )
    return True


def complete_target(
    db: Session,
    target_id: str,
    *,
    owner_id: str,
    written_fields: tuple[str, ...],
    size_bytes: int | None,
    mtime_ms: int | None,
    warning_code: str | None = None,
    now: datetime,
) -> bool:
    row = db.execute(
        select(
            MetadataWritebackTarget.operation_id,
            MetadataWritebackTarget.library_file_id,
        ).where(
            MetadataWritebackTarget.id == target_id,
            MetadataWritebackTarget.lease_owner_id == owner_id,
        )
    ).one_or_none()
    if row is None:
        return False
    if row.library_file_id and size_bytes is not None and mtime_ms is not None:
        db.execute(
            update(LibraryFile)
            .where(LibraryFile.id == row.library_file_id)
            .values(
                size_bytes=size_bytes,
                mtime_ms=mtime_ms,
                updated_at=now,
            )
        )
    return _release_target(
        db,
        target_id=target_id,
        operation_id=str(row.operation_id),
        owner_id=owner_id,
        now=now,
    )


def fail_target(
    db: Session,
    target_id: str,
    *,
    owner_id: str,
    code: str,
    summary: str,
    now: datetime,
) -> bool:
    del code, summary
    operation_id = db.scalar(
        select(MetadataWritebackTarget.operation_id).where(
            MetadataWritebackTarget.id == target_id,
            MetadataWritebackTarget.lease_owner_id == owner_id,
        )
    )
    if operation_id is None:
        return False
    return _release_target(
        db,
        target_id=target_id,
        operation_id=operation_id,
        owner_id=owner_id,
        now=now,
    )


def reconcile_queue_state(db: Session, *, now: datetime) -> int:
    active_count = int(
        db.scalar(select(func.count()).select_from(MetadataWritebackTarget)) or 0
    )
    preparation_count = int(
        db.scalar(select(func.count()).select_from(MetadataWritebackPreparation)) or 0
    )
    db.execute(
        sqlite_insert(MetadataOpfQueueState)
        .values(
            id=QUEUE_STATE_ID,
            pending_targets=active_count,
            pending_preparations=preparation_count,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[MetadataOpfQueueState.id],
            set_={
                MetadataOpfQueueState.pending_targets: active_count,
                MetadataOpfQueueState.pending_preparations: preparation_count,
                MetadataOpfQueueState.updated_at: now,
            },
        )
    )
    return active_count


def prepare_terminal_history_cleanup(
    db: Session,
    *,
    batch_size: int = 1_000,
) -> PreparedTerminalHistoryCleanup:
    terminal_ids = list(
        db.scalars(
            select(MetadataWritebackTarget.id)
            .where(MetadataWritebackTarget.status.in_(("COMPLETED", "WARNING")))
            .order_by(MetadataWritebackTarget.created_at.asc())
            .limit(batch_size)
        ).all()
    )
    statements: list[Executable] = []
    if terminal_ids:
        statements.append(
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
        statements.append(
            delete(MetadataWritebackOperation).where(
                MetadataWritebackOperation.id.in_(orphan_operation_ids)
            )
        )
    cleaned = len(terminal_ids) + len(orphan_operation_ids)
    if cleaned:
        active_count = int(
            db.scalar(
                select(func.count())
                .select_from(MetadataWritebackTarget)
                .where(MetadataWritebackTarget.id.not_in(terminal_ids))
            )
            or 0
        )
        preparation_count = int(
            db.scalar(select(func.count()).select_from(MetadataWritebackPreparation))
            or 0
        )
        now = db_timestamp()
        state_statement = sqlite_insert(MetadataOpfQueueState).values(
            id=QUEUE_STATE_ID,
            pending_targets=active_count,
            pending_preparations=preparation_count,
            updated_at=now,
        )
        statements.append(
            state_statement.on_conflict_do_update(
                index_elements=[MetadataOpfQueueState.id],
                set_={
                    MetadataOpfQueueState.pending_targets: active_count,
                    MetadataOpfQueueState.pending_preparations: preparation_count,
                    MetadataOpfQueueState.updated_at: now,
                },
            )
        )
    return PreparedTerminalHistoryCleanup(
        statements=tuple(statements),
        cleaned=cleaned,
    )


def write_prepared_terminal_history_cleanup(
    db: Session,
    prepared: PreparedTerminalHistoryCleanup,
) -> int:
    for statement in prepared.statements:
        db.execute(statement)
    return prepared.cleaned


def cleanup_terminal_history(db: Session, *, batch_size: int = 1_000) -> int:
    prepared = prepare_terminal_history_cleanup(db, batch_size=batch_size)
    return write_prepared_terminal_history_cleanup(db, prepared)


def queue_status(db: Session, *, capacity: int) -> dict[str, int | float]:
    row = db.execute(
        select(
            MetadataOpfQueueState.pending_targets,
            MetadataOpfQueueState.pending_preparations,
        ).where(MetadataOpfQueueState.id == QUEUE_STATE_ID)
    ).one_or_none()
    pending = int(row.pending_targets) if row else 0
    pending_preparations = int(row.pending_preparations) if row else 0
    return {
        "pendingTargets": pending,
        "pendingPreparations": pending_preparations,
        "capacity": capacity,
        "utilization": pending / capacity if capacity else 0.0,
    }

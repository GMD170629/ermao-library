"""ORM persistence for import task queue claim/enqueue/recovery."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, cast, insert, select, update
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import now_timestamp_ms
from app.models.import_pipeline import ImportAsset, ImportTask
from app.modules.imports.infrastructure.library_queries import (
    complete_download_task_for_source,
    fail_import_assets_for_task,
    get_import_task_by_id,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.services.audio_metadata import collect_audio_bundle_files


def find_existing_import_task(
    db: Session,
    source_path: str,
    *,
    allow_terminal_requeue: bool,
) -> dict[str, Any] | None:
    statuses = (
        ("PENDING", "PARSING")
        if allow_terminal_requeue
        else ("PENDING", "PARSING", "COMPLETED", "FAILED")
    )
    key = source_key(source_path)
    row = (
        db.execute(
            select(ImportTask.__table__)
            .where(
                (ImportTask.source_key == key)
                | (
                    ImportTask.source_key.is_(None)
                    & (ImportTask.source_path == source_path)
                ),
                ImportTask.status.in_(statuses),
            )
            .order_by(cast(ImportTask.created_at, Integer).desc(), ImportTask.id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_import_task_with_assets(
    db: Session,
    values: dict[str, Any],
    *,
    bundle_files: list[Path],
    now: Any,
) -> dict[str, Any]:
    asset_id_seed = time.time_ns()
    asset_values = [
        {
            "id": f"py_{asset_id_seed + index}",
            "importTaskId": values["id"],
            "sourcePath": str(asset_path),
            "status": "PENDING",
            "sortOrder": index,
            "createdAt": now,
            "updatedAt": now,
        }
        for index, asset_path in enumerate(bundle_files)
    ]
    db.execute(insert(ImportTask.__table__).values(values))
    task = dict(values)
    for chunk in sqlite_parameter_chunks(asset_values, parameters_per_row=7):
        db.execute(insert(ImportAsset.__table__), list(chunk))
    return get_import_task_by_id(db, str(task["id"])) or task


def stage_import_task(
    db: Session,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    library_id: str | None = None,
    media_kind_policy: str = "MIXED",
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Stage one fixed-model import task without owning the transaction."""

    source = Path(source_path).expanduser().resolve()
    now = now_timestamp_ms()
    values, bundle_files = build_import_task_values(
        task_id=f"py_{time.time_ns()}",
        source=source,
        origin=origin,
        original_name=original_name,
        requested_title=requested_title,
        requested_author=requested_author,
        library_id=library_id,
        media_kind_policy=media_kind_policy,
        message=message,
        now=now,
    )
    existing = find_existing_import_task(
        db,
        str(source),
        allow_terminal_requeue=allow_terminal_requeue,
    )
    if existing:
        return existing, False
    task = insert_import_task_with_assets(
        db,
        values,
        bundle_files=bundle_files,
        now=now,
    )
    return get_import_task_by_id(db, str(task["id"])) or task, True


def recover_stale_import_tasks(db: Session, *, now: Any, message: str) -> int:
    table = ImportTask.__table__
    values = {
        "status": "PENDING",
        "progress": 0,
        "message": message,
        "updatedAt": now,
        "leaseOwner": None,
        "leaseExpiresAt": None,
    }
    result = db.execute(update(table).where(table.c.status == "PARSING").values(values))
    return int(result.rowcount or 0)


def claim_next_import_task(
    db: Session,
    worker_id: str,
    *,
    lease_seconds: int,
    now: Any,
) -> dict[str, Any] | None:
    lease_expires = now + lease_seconds * 1000
    pending_row = (
        db.execute(
            select(ImportTask.__table__)
            .where(ImportTask.status == "PENDING")
            .order_by(cast(ImportTask.created_at, Integer).asc(), ImportTask.id.asc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    pending = dict(pending_row) if pending_row else None
    if pending is None:
        return None
    table = ImportTask.__table__
    result = db.execute(
        update(table)
        .where(table.c.id == pending["id"], table.c.status == "PENDING")
        .values(
            status="PARSING",
            leaseOwner=worker_id,
            leaseExpiresAt=lease_expires,
            attempts=int(pending.get("attempts") or 0) + 1,
            message="正在准备导入",
            updatedAt=now,
        )
    )
    if not result.rowcount:
        return None
    return get_import_task_by_id(db, str(pending["id"]))


def fail_claimed_import_task_row(
    db: Session,
    task_id: str,
    *,
    error_code: str,
    error_summary: str,
    message: str,
    retryable: bool,
    now: Any,
    expected_lease_owner: str | None = None,
) -> bool:
    table = ImportTask.__table__
    values = {
        "status": "FAILED",
        "progress": 100,
        "errorCode": error_code,
        "retryable": retryable,
        "errorSummary": error_summary,
        "message": message,
        "leaseOwner": None,
        "leaseExpiresAt": None,
        "finishedAt": now,
        "updatedAt": now,
    }
    conditions = [
        table.c.id == task_id,
        table.c.status.in_(("PENDING", "PARSING")),
    ]
    if expected_lease_owner is not None:
        conditions.append(table.c.leaseOwner == expected_lease_owner)
    result = db.execute(update(table).where(*conditions).values(values))
    if result.rowcount:
        fail_import_assets_for_task(
            db,
            task_id=task_id,
            error_code=error_code,
            error_summary=error_summary,
            updated_at=now,
        )
    return bool(result.rowcount)


def mark_download_task_completed_for_import(
    db: Session,
    *,
    source_path: str,
    book_id: str,
    updated_at: Any,
) -> None:
    complete_download_task_for_source(
        db,
        source_path=source_path,
        book_id=book_id,
        updated_at=updated_at,
    )


def build_import_task_values(
    *,
    task_id: str,
    source: Path,
    origin: str,
    original_name: str | None,
    requested_title: str | None,
    requested_author: str | None,
    library_id: str | None,
    media_kind_policy: str,
    message: str,
    now: Any,
) -> tuple[dict[str, Any], list[Path]]:
    bundle_files = collect_audio_bundle_files(source)
    is_audio_bundle = source.is_dir() and bool(bundle_files)
    values: dict[str, Any] = {
        "id": task_id,
        "libraryId": library_id,
        "mediaKindPolicy": media_kind_policy,
        "workId": None,
        "origin": origin,
        "status": "PENDING",
        "originalName": original_name or source.name,
        "requestedTitle": requested_title,
        "requestedAuthor": requested_author,
        "sourcePath": str(source),
        "sourceKey": source_key(source),
        "taskKind": "AUDIO_BUNDLE" if is_audio_bundle else "FILE",
        "bundleKey": str(source) if is_audio_bundle else None,
        "assetCount": len(bundle_files) if is_audio_bundle else 1,
        "processedAssetCount": 0,
        "progress": 0,
        "duplicate": False,
        "duration": 0,
        "errorCode": None,
        "retryable": False,
        "attempts": 0,
        "message": message,
        "createdAt": now,
        "updatedAt": now,
    }
    return values, bundle_files

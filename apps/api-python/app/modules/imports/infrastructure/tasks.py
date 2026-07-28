"""ORM persistence for import task queue claim/enqueue/recovery."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, cast, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask
from app.modules.imports.infrastructure.legacy_persistence import get_entity, legacy_insert
from app.modules.imports.infrastructure.library_queries import (
    add_work_to_shelf,
    complete_download_task_for_source,
    fail_import_assets_for_task,
    get_import_task_by_id,
    get_monitor_folder_shelf_id,
)
from app.modules.imports.infrastructure.schema import has_table, reflected_table, table_columns
from app.services.audio_metadata import collect_audio_bundle_files


def find_existing_import_task(
    db: Session,
    source_path: str,
    *,
    allow_terminal_requeue: bool,
) -> dict[str, Any] | None:
    if not has_table(db, "ImportTask"):
        return None
    statuses = ("PENDING", "PARSING") if allow_terminal_requeue else ("PENDING", "PARSING", "COMPLETED", "FAILED")
    return get_entity(
        db,
        "ImportTask",
        ImportTask.source_path == source_path,
        ImportTask.status.in_(statuses),
        order_by=(cast(ImportTask.created_at, Integer).desc(), ImportTask.id.desc()),
    )


def _filter_import_task_values(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    columns = table_columns(db, "ImportTask")
    return {key: value for key, value in values.items() if key in columns}


def insert_import_task_with_assets(
    db: Session,
    values: dict[str, Any],
    *,
    bundle_files: list[Path],
    now: Any,
) -> dict[str, Any]:
    columns = table_columns(db, "ImportTask")
    filtered = {key: value for key, value in values.items() if key in columns}
    task = legacy_insert(db, "ImportTask", filtered)
    if bundle_files and has_table(db, "ImportAsset"):
        asset_columns = table_columns(db, "ImportAsset")
        for index, asset_path in enumerate(bundle_files):
            asset_values = {
                key: value
                for key, value in {
                    "id": f"py_{time.time_ns()}",
                    "importTaskId": task["id"],
                    "sourcePath": str(asset_path),
                    "status": "PENDING",
                    "sortOrder": index,
                    "createdAt": now,
                    "updatedAt": now,
                }.items()
                if key in asset_columns
            }
            legacy_insert(db, "ImportAsset", asset_values)
    return get_import_task_by_id(db, str(task["id"])) or task


def recover_stale_import_tasks(db: Session, *, now: Any, message: str) -> int:
    if not has_table(db, "ImportTask"):
        return 0
    table = reflected_table(db, "ImportTask")
    values = _filter_import_task_values(
        db,
        {
            "status": "PENDING",
            "progress": 0,
            "message": message,
            "updatedAt": now,
            "leaseOwner": None,
            "leaseExpiresAt": None,
        },
    )
    if not values:
        return 0
    result = db.execute(update(table).where(table.c.status == "PARSING").values(values))
    return int(result.rowcount or 0)


def claim_next_import_task(
    db: Session,
    worker_id: str,
    *,
    lease_seconds: int,
    now: Any,
) -> dict[str, Any] | None:
    if not has_table(db, "ImportTask"):
        return None
    columns = table_columns(db, "ImportTask")
    lease_expires = now + lease_seconds * 1000
    pending = get_entity(
        db,
        "ImportTask",
        ImportTask.status == "PENDING",
        order_by=(cast(ImportTask.created_at, Integer).asc(), ImportTask.id.asc()),
    )
    if pending is None:
        return None
    if {"leaseOwner", "leaseExpiresAt", "attempts"}.issubset(columns):
        table = reflected_table(db, "ImportTask")
        claim_values = _filter_import_task_values(
            db,
            {
                "status": "PARSING",
                "leaseOwner": worker_id,
                "leaseExpiresAt": lease_expires,
                "attempts": int(pending.get("attempts") or 0) + 1,
                "message": "正在准备导入",
                "updatedAt": now,
            },
        )
        result = db.execute(
            update(table)
            .where(table.c.id == pending["id"], table.c.status == "PENDING")
            .values(claim_values)
        )
        if not result.rowcount:
            return None
        return get_import_task_by_id(db, str(pending["id"]))

    table = reflected_table(db, "ImportTask")
    db.execute(
        update(table)
        .where(table.c.id == pending["id"])
        .values(_filter_import_task_values(db, {"status": "PARSING"}))
    )
    return get_import_task_by_id(db, str(pending["id"]))


def fail_claimed_import_task_row(
    db: Session,
    task: dict[str, Any],
    *,
    error_code: str,
    error_summary: str,
    message: str,
    retryable: bool,
    now: Any,
) -> bool:
    table = reflected_table(db, "ImportTask")
    values = _filter_import_task_values(
        db,
        {
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
        },
    )
    result = db.execute(
        update(table)
        .where(
            table.c.id == task["id"],
            table.c.status.in_(("PENDING", "PARSING")),
        )
        .values(values)
    )
    if result.rowcount:
        fail_import_assets_for_task(
            db,
            task_id=str(task["id"]),
            error_code=error_code,
            error_summary=error_summary,
            updated_at=now,
        )
    return bool(result.rowcount)


def link_imported_work_to_monitor_shelf(
    db: Session,
    monitor_folder_id: str | None,
    work_id: str,
    *,
    created_at: Any,
) -> None:
    if not monitor_folder_id or not has_table(db, "ShelfWork") or not has_table(db, "MonitorFolder"):
        return
    shelf_id = get_monitor_folder_shelf_id(db, monitor_folder_id)
    if not shelf_id:
        return
    add_work_to_shelf(db, shelf_id, work_id, created_at=created_at)


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
    work_id: str | None,
    monitor_folder_id: str | None,
    message: str,
    now: Any,
) -> tuple[dict[str, Any], list[Path]]:
    bundle_files = collect_audio_bundle_files(source)
    is_audio_bundle = source.is_dir() and bool(bundle_files)
    values: dict[str, Any] = {
        "id": task_id,
        "monitorFolderId": monitor_folder_id,
        "workId": work_id,
        "origin": origin,
        "status": "PENDING",
        "originalName": original_name or source.name,
        "requestedTitle": requested_title,
        "requestedAuthor": requested_author,
        "sourcePath": str(source),
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

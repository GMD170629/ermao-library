"""Bounded bulk persistence for one directory-scan candidate page."""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from app.core.time import now_timestamp_ms
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportAsset, ImportTask, ImportWorkItem
from app.models.library import LibraryFile
from app.models.settings import MonitorFolder
from app.modules.imports.application.work_queue_dto import ScanBatchResult
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.tasks import build_import_task_values


def stage_scan_candidate_batch(
    db: Session,
    candidates: tuple[Path, ...],
    *,
    monitor_folder_id: str,
) -> ScanBatchResult:
    """Deduplicate and insert at most one scanner page with set-based I/O."""

    if not candidates:
        return ScanBatchResult(queued_count=0, cached_count=0)
    if len(candidates) > 500:
        raise ValueError("scan candidate batches cannot exceed 500 sources")

    canonical_paths = tuple(
        candidate.expanduser().resolve() for candidate in candidates
    )
    keys_by_path = {path: source_key(path) for path in canonical_paths}
    keys = tuple(keys_by_path.values())
    path_strings = tuple(str(path) for path in canonical_paths)
    task_rows = db.execute(
        select(ImportTask.source_key, ImportTask.source_path, ImportTask.status).where(
            or_(
                ImportTask.source_key.in_(keys),
                ImportTask.source_key.is_(None)
                & ImportTask.source_path.in_(path_strings),
            )
        )
    ).all()
    task_statuses: dict[str, set[str]] = {}
    for row_key, row_path, row_status in task_rows:
        normalized_key = str(row_key or source_key(str(row_path)))
        task_statuses.setdefault(normalized_key, set()).add(str(row_status))
    library_keys = {
        str(row_key or source_key(str(row_path)))
        for row_key, row_path in db.execute(
            select(LibraryFile.path_key, LibraryFile.path).where(
                or_(
                    LibraryFile.path_key.in_(keys),
                    LibraryFile.path_key.is_(None) & LibraryFile.path.in_(path_strings),
                )
            )
        ).all()
    }

    task_values: list[dict[str, object]] = []
    asset_values: list[dict[str, object]] = []
    work_values: list[dict[str, object]] = []
    now_ms = now_timestamp_ms()
    now = db_timestamp()
    media_kind_policy = (
        db.scalar(
            select(MonitorFolder.media_kind_policy).where(
                MonitorFolder.id == monitor_folder_id
            )
        )
        or "MIXED"
    )
    unique_batch_keys: set[str] = set()
    for index, path in enumerate(canonical_paths):
        key = keys_by_path[path]
        statuses = task_statuses.get(key, set())
        already_known = (
            key in unique_batch_keys or key in library_keys or bool(statuses)
        )
        if already_known:
            continue
        unique_batch_keys.add(key)
        task_id = f"py_{time.time_ns()}_{index}"
        values, bundle_files = build_import_task_values(
            task_id=task_id,
            source=path,
            origin="WATCH",
            original_name=path.name,
            requested_title=None,
            requested_author=None,
            monitor_folder_id=monitor_folder_id,
            media_kind_policy=str(media_kind_policy),
            message="扫描文件已进入导入队列",
            now=now_ms,
        )
        task_values.append(values)
        for sort_order, asset_path in enumerate(bundle_files):
            asset_values.append(
                {
                    "id": f"py_{time.time_ns()}_{sort_order}",
                    "importTaskId": task_id,
                    "sourcePath": str(asset_path),
                    "status": "PENDING",
                    "sortOrder": sort_order,
                    "createdAt": now_ms,
                    "updatedAt": now_ms,
                }
            )
        work_values.append(
            {
                "id": f"work_{time.time_ns()}_{index}",
                "kind": "IMPORT_SOURCE",
                "scanJobId": None,
                "importTaskId": task_id,
                "dedupeKey": f"import:{key}:{task_id}",
                "status": "PENDING",
                "priority": 10,
                "availableAt": now,
                "attempts": 0,
                "createdAt": now,
                "updatedAt": now,
            }
        )

    if task_values:
        db.execute(insert(ImportTask.__table__), task_values)
    if asset_values:
        db.execute(insert(ImportAsset.__table__), asset_values)
    if work_values:
        db.execute(insert(ImportWorkItem.__table__), work_values)
    db.flush()
    queued_count = len(task_values)
    return ScanBatchResult(
        queued_count=queued_count,
        cached_count=len(canonical_paths) - queued_count,
    )

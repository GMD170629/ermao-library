"""Bounded bulk persistence for one directory-scan candidate page."""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.import_pipeline import ImportAsset, ImportTask, ImportWorkItem
from app.models.library import LibraryFile
from app.modules.imports.application.work_queue_dto import (
    PreparedScanCandidateBatch,
    PreparedScanSources,
    ScanBatchResult,
    ScanCandidateProjection,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.tasks import build_import_task_values


def prepare_scan_sources(
    candidates: tuple[Path, ...],
) -> PreparedScanSources:
    """Resolve scanner paths before a database Session is opened."""

    if not candidates:
        return PreparedScanSources((), ())
    if len(candidates) > 500:
        raise ValueError("scan candidate batches cannot exceed 500 sources")
    canonical_paths = tuple(
        candidate.expanduser().resolve() for candidate in candidates
    )
    keys_by_path = {path: source_key(path) for path in canonical_paths}
    source_pairs = tuple((keys_by_path[path], str(path)) for path in canonical_paths)
    return PreparedScanSources(canonical_paths, source_pairs)


def load_scan_candidate_projection(
    db: Session,
    sources: PreparedScanSources,
    *,
    library_id: str,
) -> ScanCandidateProjection:
    """Load only the SQL projection needed to prepare a scanner page."""

    if not sources.source_pairs:
        return ScanCandidateProjection((), (), "MIXED")
    task_rows: list[tuple[str | None, str, str]] = []
    for pair_chunk in sqlite_parameter_chunks(sources.source_pairs, parameters_per_row=2):
        chunk_keys = tuple(key for key, _path in pair_chunk)
        chunk_paths = tuple(path for _key, path in pair_chunk)
        task_rows.extend(
            db.execute(
                select(
                    ImportTask.source_key,
                    ImportTask.source_path,
                    ImportTask.status,
                ).where(
                    or_(
                        ImportTask.source_key.in_(chunk_keys),
                        ImportTask.source_key.is_(None)
                        & ImportTask.source_path.in_(chunk_paths),
                    )
                )
            ).all()
        )
    library_rows: list[tuple[str | None, str]] = []
    for pair_chunk in sqlite_parameter_chunks(sources.source_pairs, parameters_per_row=2):
        chunk_keys = tuple(key for key, _path in pair_chunk)
        chunk_paths = tuple(path for _key, path in pair_chunk)
        library_rows.extend(
            db.execute(
                select(LibraryFile.path_key, LibraryFile.path).where(
                    or_(
                        LibraryFile.path_key.in_(chunk_keys),
                        LibraryFile.path_key.is_(None)
                        & LibraryFile.path.in_(chunk_paths),
                    )
                )
            ).all()
        )
    return ScanCandidateProjection(
        task_sources=tuple(task_rows),
        library_sources=tuple(library_rows),
        media_kind_policy="MIXED",
    )


def prepare_scan_candidate_batch(
    sources: PreparedScanSources,
    projection: ScanCandidateProjection,
    *,
    library_id: str,
    now_ms: int,
    now: object,
) -> PreparedScanCandidateBatch:
    """Build every import/task/work row after the projection Session is closed."""

    task_statuses: dict[str, set[str]] = {}
    for row_key, row_path, row_status in projection.task_sources:
        normalized_key = str(row_key or source_key(str(row_path)))
        task_statuses.setdefault(normalized_key, set()).add(str(row_status))
    library_keys = {
        str(row_key or source_key(str(row_path)))
        for row_key, row_path in projection.library_sources
    }
    keys_by_path = {
        path: key
        for path, (key, _path_text) in zip(
            sources.canonical_paths, sources.source_pairs, strict=True
        )
    }

    task_values: list[dict[str, object]] = []
    asset_values: list[dict[str, object]] = []
    work_values: list[dict[str, object]] = []
    unique_batch_keys: set[str] = set()
    id_seed = time.time_ns()
    for index, path in enumerate(sources.canonical_paths):
        key = keys_by_path[path]
        statuses = task_statuses.get(key, set())
        already_known = (
            key in unique_batch_keys or key in library_keys or bool(statuses)
        )
        if already_known:
            continue
        unique_batch_keys.add(key)
        task_id = f"py_{id_seed}_{index}"
        values, bundle_files = build_import_task_values(
            task_id=task_id,
            source=path,
            origin="WATCH",
            original_name=path.name,
            requested_title=None,
            requested_author=None,
            library_id=library_id,
            media_kind_policy=projection.media_kind_policy,
            message="扫描文件已进入导入队列",
            now=now_ms,
        )
        task_values.append(values)
        for sort_order, asset_path in enumerate(bundle_files):
            asset_values.append(
                {
                    "id": f"py_{id_seed}_{index}_{sort_order}",
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
                "id": f"work_{id_seed}_{index}",
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

    queued_count = len(task_values)
    return PreparedScanCandidateBatch(
        task_rows=tuple(task_values),
        asset_rows=tuple(asset_values),
        work_rows=tuple(work_values),
        result=ScanBatchResult(
            queued_count=queued_count,
            cached_count=len(sources.canonical_paths) - queued_count,
        ),
    )


def write_prepared_scan_candidate_batch(
    db: Session,
    prepared: PreparedScanCandidateBatch,
) -> ScanBatchResult:
    """Execute only bounded collection inserts for one prepared scanner page."""

    for chunk in sqlite_parameter_chunks(
        prepared.task_rows,
        parameters_per_row=len(prepared.task_rows[0]) if prepared.task_rows else 1,
    ):
        db.execute(insert(ImportTask.__table__), list(chunk))
    for chunk in sqlite_parameter_chunks(prepared.asset_rows, parameters_per_row=7):
        db.execute(insert(ImportAsset.__table__), list(chunk))
    for chunk in sqlite_parameter_chunks(prepared.work_rows, parameters_per_row=11):
        db.execute(insert(ImportWorkItem.__table__), list(chunk))
    return prepared.result

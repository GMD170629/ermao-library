"""Bounded bulk persistence for one directory-scan candidate page."""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.import_pipeline import ImportAsset, ImportTask, ImportWorkItem
from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.imports.application.work_queue_dto import (
    PreparedScanCandidateBatch,
    PreparedScanSources,
    ScanBatchResult,
    ScanCandidateProjection,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.modules.imports.infrastructure.tasks import build_import_task_values
from app.modules.imports.infrastructure.topology_scan import prepare_topology_sources
from app.services.book_identity import normalize_identity_part


def prepare_scan_sources(
    candidates: tuple[Path, ...],
    *,
    library_root: Path,
    organization_mode: str,
) -> PreparedScanSources:
    """Resolve scanner paths before a database Session is opened."""

    return prepare_topology_sources(
        candidates,
        library_root=library_root,
        organization_mode=organization_mode,
    )


def load_scan_candidate_projection(
    db: Session,
    sources: PreparedScanSources,
    *,
    library_id: str,
) -> ScanCandidateProjection:
    """Load only the SQL projection needed to prepare a scanner page."""

    if not sources.source_pairs:
        return ScanCandidateProjection((), (), (), (), (), "MIXED")
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
    work_source_keys = tuple(
        {source.work_source_key for source in sources.topology_sources}
    )
    topology_works = tuple(
        (str(source_key_value), str(work_id))
        for source_key_value, work_id in db.execute(
            select(LibraryWork.source_key, LibraryWork.id).where(
                LibraryWork.library_id == library_id,
                LibraryWork.source_key.in_(work_source_keys),
            )
        ).all()
        if source_key_value is not None
    )
    topology_versions = tuple(
        (str(work_source_key), str(version_source_key), str(version_id))
        for work_source_key, version_source_key, version_id in db.execute(
            select(
                LibraryWork.source_key,
                LibraryVersion.source_key,
                LibraryVersion.id,
            )
            .join(LibraryVersion, LibraryVersion.work_id == LibraryWork.id)
            .where(
                LibraryWork.library_id == library_id,
                LibraryWork.source_key.in_(work_source_keys),
            )
        ).all()
        if work_source_key is not None
    )
    topology_volumes = tuple(
        (
            str(work_source_key),
            str(version_source_key),
            str(volume_resource_key),
            str(volume_id),
        )
        for (
            work_source_key,
            version_source_key,
            volume_resource_key,
            volume_id,
        ) in db.execute(
            select(
                LibraryWork.source_key,
                LibraryVersion.source_key,
                LibraryVolume.resource_key,
                LibraryVolume.id,
            )
            .join(LibraryVersion, LibraryVersion.work_id == LibraryWork.id)
            .join(LibraryVolume, LibraryVolume.version_id == LibraryVersion.id)
            .where(
                LibraryWork.library_id == library_id,
                LibraryWork.source_key.in_(work_source_keys),
            )
        ).all()
        if work_source_key is not None
    )
    return ScanCandidateProjection(
        task_sources=tuple(task_rows),
        library_sources=tuple(library_rows),
        topology_works=topology_works,
        topology_versions=topology_versions,
        topology_volumes=topology_volumes,
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
    existing_work_ids = dict(projection.topology_works)
    existing_version_ids = {
        (work_source_key, version_source_key): version_id
        for work_source_key, version_source_key, version_id in (
            projection.topology_versions
        )
    }
    existing_volume_ids = {
        (work_source_key, version_source_key, volume_resource_key): volume_id
        for (
            work_source_key,
            version_source_key,
            volume_resource_key,
            volume_id,
        ) in projection.topology_volumes
    }

    topology_work_values: list[dict[str, object]] = []
    topology_version_values: list[dict[str, object]] = []
    topology_volume_values: list[dict[str, object]] = []
    task_values: list[dict[str, object]] = []
    asset_values: list[dict[str, object]] = []
    work_values: list[dict[str, object]] = []
    unique_batch_keys: set[str] = set()
    id_seed = time.time_ns()
    work_ids = dict(existing_work_ids)
    version_ids = dict(existing_version_ids)
    volume_ids = dict(existing_volume_ids)
    for index, topology_source in enumerate(sources.topology_sources):
        path = topology_source.source_path
        key = topology_source.source_key
        work_id = work_ids.get(topology_source.work_source_key)
        if work_id is None:
            work_id = f"topology_work_{id_seed}_{len(work_ids)}"
            work_ids[topology_source.work_source_key] = work_id
            topology_work_values.append(
                {
                    "id": work_id,
                    "libraryId": library_id,
                    "origin": "WATCH",
                    "sourceKey": topology_source.work_source_key,
                    "title": topology_source.work_title,
                    "normalizedTitle": normalize_identity_part(
                        topology_source.work_title
                    ),
                    "author": None,
                    "normalizedAuthor": None,
                    "tags": "[]",
                    "organizeStatus": "APPLIED",
                    "organized": True,
                    "createdAt": now_ms,
                    "updatedAt": now_ms,
                }
            )
        version_identity = (
            topology_source.work_source_key,
            topology_source.version_source_key,
        )
        version_id = version_ids.get(version_identity)
        if version_id is None:
            version_id = f"topology_version_{id_seed}_{len(version_ids)}"
            version_ids[version_identity] = version_id
            topology_version_values.append(
                {
                    "id": version_id,
                    "workId": work_id,
                    "sourceKey": topology_source.version_source_key,
                    "sourceName": topology_source.version_name,
                    "createdAt": now_ms,
                    "updatedAt": now_ms,
                }
            )
        volume_identity = (
            topology_source.work_source_key,
            topology_source.version_source_key,
            topology_source.volume_resource_key,
        )
        volume_id = volume_ids.get(volume_identity)
        volume_existed = volume_id is not None
        if volume_id is None:
            volume_id = f"topology_volume_{id_seed}_{len(volume_ids)}"
            volume_ids[volume_identity] = volume_id
            topology_volume_values.append(
                {
                    "id": volume_id,
                    "versionId": version_id,
                    "origin": "WATCH",
                    "title": topology_source.volume_title,
                    "sortOrder": topology_source.volume_sort_order,
                    "format": topology_source.volume_format,
                    "classificationSource": "MONITOR_FOLDER",
                    "classificationReason": "DIRECTORY_LAYOUT",
                    "resourceKey": topology_source.volume_resource_key,
                    "importStatus": "PENDING",
                    "sizeBytes": 0,
                    "coverStatus": "PENDING",
                    "hidden": False,
                    "createdAt": now_ms,
                    "updatedAt": now_ms,
                }
            )
        statuses = task_statuses.get(key, set())
        already_known = (
            key in unique_batch_keys
            or key in library_keys
            or bool(statuses)
            or volume_existed
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
        values["workId"] = work_id
        values["volumeId"] = volume_id
        task_values.append(values)
        prepared_assets = tuple(bundle_files)
        for sort_order, asset_path in enumerate(prepared_assets):
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
        topology_work_rows=tuple(topology_work_values),
        topology_version_rows=tuple(topology_version_values),
        topology_volume_rows=tuple(topology_volume_values),
        task_rows=tuple(task_values),
        asset_rows=tuple(asset_values),
        work_rows=tuple(work_values),
        result=ScanBatchResult(
            queued_count=queued_count,
            cached_count=len(sources.topology_sources) - queued_count,
            rejected_count=sources.rejected_count,
            errors=sources.errors,
        ),
    )


def write_prepared_scan_candidate_batch(
    db: Session,
    prepared: PreparedScanCandidateBatch,
) -> ScanBatchResult:
    """Execute only bounded collection inserts for one prepared scanner page."""

    for chunk in sqlite_parameter_chunks(
        prepared.topology_work_rows,
        parameters_per_row=(
            len(prepared.topology_work_rows[0]) if prepared.topology_work_rows else 1
        ),
    ):
        db.execute(insert(LibraryWork.__table__), list(chunk))
    for chunk in sqlite_parameter_chunks(
        prepared.topology_version_rows,
        parameters_per_row=(
            len(prepared.topology_version_rows[0])
            if prepared.topology_version_rows
            else 1
        ),
    ):
        db.execute(insert(LibraryVersion.__table__), list(chunk))
    for chunk in sqlite_parameter_chunks(
        prepared.topology_volume_rows,
        parameters_per_row=(
            len(prepared.topology_volume_rows[0])
            if prepared.topology_volume_rows
            else 1
        ),
    ):
        db.execute(insert(LibraryVolume.__table__), list(chunk))
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

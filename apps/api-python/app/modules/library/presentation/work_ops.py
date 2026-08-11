"""Library work deletion and folder-tree helpers for HTTP adapters."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_http_store
from app.bootstrap.library import (
    delete_prepared_library_works,
    library_deletion,
    library_join_queries,
    library_storage,
)
from app.bootstrap.media import media_streaming
from app.core.config import Settings
from app.modules.library.application.work_deletion import (
    PreparedFileQuarantineEntry,
    PreparedLibraryWorkDeletion,
)
from app.modules.system.public import PreparedSystemEvent

logger = logging.getLogger(__name__)
_stored_path = media_streaming.stored_path


def _now() -> datetime:
    return datetime.now(UTC)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except SQLAlchemyError:
        return False


def _storage_managed_path(path_value: str | None, settings: Settings) -> Path | None:
    path = _stored_path(path_value, settings)
    if not path:
        return None
    try:
        storage = settings.resolved_storage_root.resolve()
        resolved = path.resolve()
    except OSError:
        return None
    if resolved == storage or storage in resolved.parents:
        return resolved
    return None


def _collect_work_storage_paths(
    db: Session, work_id: str, settings: Settings
) -> list[Path]:
    paths: list[Path] = []

    def add(path_value: str | None) -> None:
        path = _storage_managed_path(path_value, settings)
        if path:
            paths.append(path)

    work_cover, _media_versions, volumes, files = (
        library_storage.collect_storage_values(db, work_id)
    )
    add(work_cover)
    for volume in volumes:
        add(volume.get("coverPath"))
    for file in files:
        add(file.get("path"))
    return list(dict.fromkeys(paths))


def _delete_storage_paths(paths: list[Path], settings: Settings) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    storage = settings.resolved_storage_root.resolve()
    for path in paths:
        try:
            resolved = path.resolve()
            if resolved != storage and storage not in resolved.parents:
                continue
            if resolved.is_file() or resolved.is_symlink():
                resolved.unlink()
                deleted.append(str(resolved))
                parent = resolved.parent
                while parent != storage and storage in parent.parents:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        except OSError as exc:
            failed.append({"path": str(path), "message": str(exc)})
            logger.warning(
                "failed to delete managed storage file: %s", path, exc_info=exc
            )
    return {"deletedFiles": len(deleted), "failedFileDeletes": failed}


def _monitor_source_roots(db: Session, settings: Settings) -> list[Path]:
    roots: list[Path] = []
    roots.extend(
        Path(root_path).expanduser()
        for root_path in import_http_store.list_monitor_root_paths(db)
        if root_path.strip()
    )
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(root.resolve())
        except OSError:
            continue
    return list(dict.fromkeys(resolved))


def _source_delete_roots(db: Session, settings: Settings) -> list[Path]:
    return list(
        dict.fromkeys(
            [settings.resolved_storage_root, *_monitor_source_roots(db, settings)]
        )
    )


def _source_delete_path(
    path_value: str | None,
    db: Session,
    settings: Settings,
    roots: list[Path] | None = None,
) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if roots is None and path.is_absolute():
        return resolved
    allowed_roots = roots if roots is not None else _source_delete_roots(db, settings)
    if any(resolved != root and root in resolved.parents for root in allowed_roots):
        return resolved
    return None


def _collect_work_source_paths(
    db: Session, work_id: str, settings: Settings
) -> list[Path]:
    paths: list[Path] = []

    def add(path_value: str | None, roots: list[Path]) -> None:
        path = _source_delete_path(path_value, db, settings, roots)
        if path:
            paths.append(path)

    for source_path in import_http_store.list_import_source_paths_for_work(db, work_id):
        try:
            database_path = Path(source_path).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if database_path.is_absolute():
            paths.append(database_path)
    # Older records may not retain an ImportTask link. In that case a library
    # file living in a monitor folder is the best available source-file signal.
    if not paths and _has_table(db, "LibraryFile"):
        monitor_roots = _monitor_source_roots(db, settings)
        for path_value in library_join_queries.list_file_paths_for_work(db, work_id):
            add(path_value, monitor_roots)
    return list(dict.fromkeys(paths))


def _delete_source_paths(paths: list[Path]) -> dict[str, Any]:
    deleted: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []
    for path in paths:
        try:
            if not path.exists() and not path.is_symlink():
                missing.append(str(path))
                continue
            if not path.is_file() and not path.is_symlink():
                failed.append({"path": str(path), "message": "目标不是文件"})
                continue
            path.unlink()
            deleted.append(str(path))
        except OSError as exc:
            failed.append({"path": str(path), "message": str(exc)})
            logger.warning("failed to delete source file: %s", path, exc_info=exc)
    return {
        "deletedFiles": len(deleted),
        "missingFiles": missing,
        "failedFileDeletes": failed,
    }


def _conversion_output_paths(
    conversion: dict[str, Any] | None, settings: Settings
) -> list[Path]:
    output_value = (conversion or {}).get("outputPath")
    if not output_value:
        return []
    try:
        output = Path(str(output_value)).expanduser().resolve()
        conversion_root = settings.conversion_root.resolve()
    except OSError:
        return []
    if output == conversion_root or conversion_root not in output.parents:
        return []
    paths = [output]
    sidecar = output.with_name("normalization.json")
    if sidecar.exists() or sidecar.is_symlink():
        paths.append(sidecar)
    return paths


def _delete_work_records(db: Session, work_id: str) -> dict[str, Any]:
    return library_deletion.delete_work_records(db, work_id)


def _delete_work_and_storage(
    db: Session,
    work_id: str,
    settings: Settings,
    *,
    delete_source: bool = False,
    events: tuple[PreparedSystemEvent, ...] = (),
) -> dict[str, Any]:
    result = _delete_works_and_storage(
        db,
        (work_id,),
        settings,
        delete_source=delete_source,
        events=events,
    )
    return {**result, "id": work_id}


def _delete_works_and_storage(
    db: Session,
    work_ids: tuple[str, ...],
    settings: Settings,
    *,
    delete_source: bool = False,
    events: tuple[PreparedSystemEvent, ...] = (),
) -> dict[str, Any]:
    managed_paths = list(
        dict.fromkeys(
            path
            for work_id in work_ids
            for path in _collect_work_storage_paths(db, work_id, settings)
        )
    )
    source_paths = list(
        dict.fromkeys(
            path
            for work_id in work_ids
            for path in _collect_work_source_paths(db, work_id, settings)
        )
    )
    managed_paths = [path for path in managed_paths if path not in source_paths]
    operation_id = f"delete_{time_ns()}"
    quarantine_entries: list[PreparedFileQuarantineEntry] = []
    for index, path in enumerate(managed_paths):
        quarantine_root = (
            settings.resolved_storage_root / ".shuku-starship-quarantine" / operation_id
        )
        quarantine_entries.append(
            PreparedFileQuarantineEntry(
                original_path=str(path),
                quarantine_path=str(quarantine_root / f"{index}_{path.name}"),
                quarantine_root=str(quarantine_root),
                source_file=False,
            )
        )
    if delete_source:
        for index, path in enumerate(source_paths):
            quarantine_root = path.parent / ".shuku-starship-quarantine" / operation_id
            quarantine_entries.append(
                PreparedFileQuarantineEntry(
                    original_path=str(path),
                    quarantine_path=str(
                        quarantine_root / f"source_{index}_{path.name}"
                    ),
                    quarantine_root=str(quarantine_root),
                    source_file=True,
                )
            )
    outcome = delete_prepared_library_works(
        db,
        PreparedLibraryWorkDeletion(
            work_ids=work_ids,
            files=tuple(quarantine_entries),
            events=events,
        ),
    )
    return {
        "deleted": bool(outcome.deleted),
        "deleteSource": delete_source,
        "deletedDatabaseRecords": outcome.deleted,
        "deletedFiles": outcome.isolated_files,
        "deletedSourceFiles": outcome.deleted_source_files,
        "missingSourceFiles": list(outcome.missing_source_paths),
        "failedFileDeletes": list(outcome.failed_file_deletes),
    }


def _delete_import_linked_library_scope(
    db: Session,
    task: dict[str, Any],
    settings: Settings,
    conversion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Delete the volume resolved from a completed import task's exact file path."""

    target = _resolve_import_linked_volume_target(db, task, conversion, settings)
    if target is None:
        return {
            "deleted": False,
            "deletedWorkRecord": False,
            "deletedDatabaseRecords": 0,
            "deletedFiles": 0,
            "failedFileDeletes": [],
            "workId": None,
        }

    deleted_records = library_deletion.delete_volume_scope(db, target.volume_id)
    # The volume deletion adapter removes an empty media version and then an
    # empty work. Checking the work directly avoids inferring identity from a
    # repeated or absent volume number.
    deleted_work = not library_deletion.work_exists(db, target.work_id)
    return {
        "deleted": deleted_records == 1,
        "deletedWorkRecord": deleted_work,
        "deletedDatabaseRecords": deleted_records,
        "deletedFiles": 0,
        "failedFileDeletes": [],
        "workId": target.work_id,
    }


def _collect_import_linked_library_scope_paths(
    db: Session,
    task: dict[str, Any],
    settings: Settings,
    conversion: dict[str, Any] | None = None,
) -> list[Path]:
    """Collect managed files for the import task's exact volume target."""

    target = _resolve_import_linked_volume_target(db, task, conversion, settings)
    if target is None:
        return []

    paths: list[Path] = []

    def add_path(value: object) -> None:
        path = _storage_managed_path(str(value), settings) if value else None
        if path:
            paths.append(path)

    add_path(target.cover_path)
    for file in library_deletion.list_files_for_volume(db, target.volume_id):
        add_path(file.get("path"))
    return list(dict.fromkeys(paths))


def _resolve_import_linked_volume_target(
    db: Session,
    task: dict[str, Any],
    conversion: dict[str, Any] | None,
    settings: Settings,
) -> library_deletion.VolumeDeletionTarget | None:
    file_paths: list[str] = []
    for value in (
        (conversion or {}).get("outputPath"),
        task.get("sourcePath"),
    ):
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = settings.resolved_storage_root / path
        raw_path = str(path)
        try:
            resolved_path = str(path.resolve())
        except (OSError, RuntimeError):
            resolved_path = raw_path
        for candidate in (resolved_path, raw_path):
            if candidate not in file_paths:
                file_paths.append(candidate)

    target = library_deletion.find_volume_deletion_target_by_file_paths(db, file_paths)
    if target is not None:
        return target

    # Compatibility for older completed tasks whose source was copied or moved
    # after import. The volume identifier remains precise and does not require a
    # potentially stale work identifier.
    volume_id = str(task.get("volumeId") or "").strip()
    return (
        library_deletion.find_volume_deletion_target_by_id(db, volume_id)
        if volume_id
        else None
    )


def _path_tree(paths: list[str], root_label: str) -> dict[str, Any]:
    root = {
        "name": root_label,
        "path": root_label,
        "type": "folder",
        "children": [],
        "fileCount": 0,
        "sizeBytes": 0,
    }
    children_by_path: dict[str, dict[str, Any]] = {root_label: root}
    for raw_path in sorted({path for path in paths if path}):
        parts = [part for part in Path(raw_path).parts if part not in {"/", ""}]
        current = root
        current_path = root_label
        for index, part in enumerate(parts):
            current_path = f"{current_path}/{part}"
            node = children_by_path.get(current_path)
            if not node:
                node = {
                    "name": part,
                    "path": current_path,
                    "type": "file" if index == len(parts) - 1 else "folder",
                    "children": [],
                    "fileCount": 0,
                    "sizeBytes": 0,
                }
                children_by_path[current_path] = node
                current["children"].append(node)
            current = node
            current["fileCount"] = int(current.get("fileCount") or 0) + (
                1 if index == len(parts) - 1 else 0
            )
    return root


def _source_folder_preview(root_path: str) -> dict[str, Any]:
    path = Path(root_path)
    readable = path.exists() and path.is_dir() and os.access(path, os.R_OK)
    writable = path.exists() and path.is_dir() and os.access(path, os.W_OK)
    children: list[dict[str, Any]] = []
    if readable:
        try:
            for child in sorted(
                path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )[:80]:
                try:
                    stat = child.stat()
                    children.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "type": "folder" if child.is_dir() else "file",
                            "sizeBytes": 0 if child.is_dir() else stat.st_size,
                            "mtimeMs": int(stat.st_mtime * 1000),
                        }
                    )
                except OSError:
                    children.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "type": "unknown",
                            "sizeBytes": 0,
                            "error": "无法读取",
                        }
                    )
        except OSError:
            readable = False
    return {"readable": readable, "writable": writable, "children": children}

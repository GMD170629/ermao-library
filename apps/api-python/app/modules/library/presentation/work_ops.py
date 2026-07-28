"""Library work deletion and folder-tree helpers for HTTP adapters."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_http_store
from app.bootstrap.library import library_deletion, library_join_queries, library_storage
from app.bootstrap.media import media_streaming
from app.core.config import Settings
from app.modules.library.presentation.views import _preferred_work_cover_path
from app.services.default_cover import cover_status, ensure_default_cover

logger = logging.getLogger(__name__)
_stored_path = media_streaming.stored_path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
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


def _collect_work_storage_paths(db: Session, work_id: str, settings: Settings) -> list[Path]:
    paths: list[Path] = []

    def add(path_value: str | None) -> None:
        path = _storage_managed_path(path_value, settings)
        if path:
            paths.append(path)

    work_cover, editions, volumes, files = library_storage.collect_storage_values(
        db, work_id
    )
    add(work_cover)
    for edition in editions:
        add(edition.get("coverPath"))
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
            logger.warning("failed to delete managed storage file: %s", path, exc_info=exc)
    return {"deletedFiles": len(deleted), "failedFileDeletes": failed}


def _monitor_source_roots(db: Session, settings: Settings) -> list[Path]:
    roots: list[Path] = []
    if settings.resolved_monitor_root:
        roots.append(settings.resolved_monitor_root)
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
    return list(dict.fromkeys([settings.resolved_storage_root, *_monitor_source_roots(db, settings)]))


def _source_delete_path(path_value: str | None, db: Session, settings: Settings, roots: list[Path] | None = None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    allowed_roots = roots if roots is not None else _source_delete_roots(db, settings)
    if any(resolved != root and root in resolved.parents for root in allowed_roots):
        return resolved
    return None


def _collect_work_source_paths(db: Session, work_id: str, settings: Settings) -> list[Path]:
    paths: list[Path] = []
    delete_roots = _source_delete_roots(db, settings)

    def add(path_value: str | None, roots: list[Path]) -> None:
        path = _source_delete_path(path_value, db, settings, roots)
        if path:
            paths.append(path)

    for source_path in import_http_store.list_import_source_paths_for_work(
        db, work_id
    ):
        add(source_path, delete_roots)
    # Older records may not retain an ImportTask link. In that case a library
    # file living in a monitor folder is the best available source-file signal.
    if not paths and _has_table(db, "LibraryEdition") and _has_table(db, "LibraryFile"):
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
    return {"deletedFiles": len(deleted), "missingFiles": missing, "failedFileDeletes": failed}


def _conversion_output_paths(conversion: dict[str, Any] | None, settings: Settings) -> list[Path]:
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


def _delete_work_and_storage(db: Session, work_id: str, settings: Settings, *, delete_source: bool = False) -> dict[str, Any]:
    managed_paths = _collect_work_storage_paths(db, work_id, settings)
    source_paths = _collect_work_source_paths(db, work_id, settings)
    managed_paths = [path for path in managed_paths if path not in source_paths]
    record_cleanup = _delete_work_records(db, work_id)
    deleted = bool(record_cleanup["deleted"])
    if deleted:
        db.commit()
    managed_cleanup = _delete_storage_paths(managed_paths, settings) if deleted else {"deletedFiles": 0, "failedFileDeletes": []}
    source_cleanup = _delete_source_paths(source_paths) if deleted and delete_source else {"deletedFiles": 0, "missingFiles": [], "failedFileDeletes": []}
    return {
        "deleted": deleted,
        "id": work_id,
        "deleteSource": delete_source,
        "deletedDatabaseRecords": record_cleanup["deletedDatabaseRecords"],
        "deletedFiles": int(managed_cleanup["deletedFiles"]) + int(source_cleanup["deletedFiles"]),
        "deletedSourceFiles": source_cleanup["deletedFiles"],
        "missingSourceFiles": source_cleanup["missingFiles"],
        "failedFileDeletes": [*managed_cleanup["failedFileDeletes"], *source_cleanup["failedFileDeletes"]],
    }


def _delete_import_linked_library_scope(
    db: Session,
    task: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Delete only the volume/edition produced by one import task.

    The parent work is retained while any edition remains. This deliberately
    avoids the work-wide cleanup used by the library's explicit delete action.
    """

    work_id = str(task.get("workId") or "").strip()
    edition_id = str(task.get("editionId") or "").strip()
    volume_id = str(task.get("volumeId") or "").strip()
    if not work_id or not edition_id or not _has_table(db, "LibraryEdition"):
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    edition = library_deletion.get_edition_for_work(db, edition_id=edition_id, work_id=work_id)
    if not edition:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    managed_paths: list[Path] = []
    deleted_records = 0

    def add_path(value: Any) -> None:
        path = _storage_managed_path(str(value), settings) if value else None
        if path:
            managed_paths.append(path)

    deleted_scope = False
    if volume_id and _has_table(db, "LibraryVolume"):
        volume = library_deletion.get_volume_for_edition(
            db, volume_id=volume_id, edition_id=edition_id
        )
        if volume:
            files = library_deletion.list_files_for_volume(db, volume_id)
            add_path(volume.get("coverPath"))
            for item in files:
                add_path(item.get("path"))
            deleted_records += library_deletion.delete_volume_scope(db, volume_id)
            deleted_scope = True

            remaining_volumes = library_deletion.count_volumes_for_edition(db, edition_id)
            remaining_files = library_deletion.count_files_for_edition(db, edition_id)
            if remaining_volumes == 0 and remaining_files == 0:
                files = library_deletion.list_files_for_edition(db, edition_id)
                volumes = library_deletion.list_volume_covers_for_edition(db, edition_id)
                add_path(edition.get("coverPath"))
                for item in files:
                    add_path(item.get("path"))
                for item in volumes:
                    add_path(item.get("coverPath"))
                deleted_records += library_deletion.delete_edition_scope(db, edition_id)
    else:
        files = library_deletion.list_files_for_edition(db, edition_id)
        volumes = library_deletion.list_volume_covers_for_edition(db, edition_id)
        add_path(edition.get("coverPath"))
        for item in files:
            add_path(item.get("path"))
        for item in volumes:
            add_path(item.get("coverPath"))
        deleted_records += library_deletion.delete_edition_scope(db, edition_id)
        deleted_scope = True

    if not deleted_scope:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    remaining_editions = library_deletion.count_editions_for_work(db, work_id)
    deleted_work = remaining_editions == 0
    if deleted_work:
        work_cleanup = _delete_work_records(db, work_id)
        deleted_records += int(work_cleanup.get("deletedDatabaseRecords") or 0)
    else:
        primary_id = library_deletion.preferred_primary_edition_id(db, work_id)
        if primary_id:
            library_deletion.set_work_primary_edition(db, work_id=work_id, primary_id=primary_id)
        cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
        library_deletion.update_work_after_scope_delete(
            db,
            work_id=work_id,
            primary_id=primary_id,
            cover_path=cover_path,
            cover_status=cover_status(cover_path, settings),
            now=_now(),
        )
    return {
        "deleted": True,
        "deletedWorkRecord": deleted_work,
        "deletedDatabaseRecords": deleted_records,
        "deletedFiles": 0,
        "failedFileDeletes": [],
    }


def _collect_import_linked_library_scope_paths(
    db: Session,
    task: dict[str, Any],
    settings: Settings,
) -> list[Path]:
    """Collect files removed by ``_delete_import_linked_library_scope``.

    This read-only projection runs before any database mutation so callers can
    quarantine the files and restore them if the transaction fails.
    """

    work_id = str(task.get("workId") or "").strip()
    edition_id = str(task.get("editionId") or "").strip()
    volume_id = str(task.get("volumeId") or "").strip()
    if not work_id or not edition_id:
        return []
    edition = library_deletion.get_edition_for_work(
        db, edition_id=edition_id, work_id=work_id
    )
    if not edition:
        return []

    paths: list[Path] = []

    def add_path(value: Any) -> None:
        path = _storage_managed_path(str(value), settings) if value else None
        if path:
            paths.append(path)

    if volume_id:
        volume = library_deletion.get_volume_for_edition(
            db, volume_id=volume_id, edition_id=edition_id
        )
        if not volume:
            return []
        files = library_deletion.list_files_for_volume(db, volume_id)
        add_path(volume.get("coverPath"))
        for item in files:
            add_path(item.get("path"))
        edition_file_count = library_deletion.count_files_for_edition(db, edition_id)
        volume_count = library_deletion.count_volumes_for_edition(db, edition_id)
        if volume_count == 1 and edition_file_count == len(files):
            add_path(edition.get("coverPath"))
            for item in library_deletion.list_files_for_edition(db, edition_id):
                add_path(item.get("path"))
            for item in library_deletion.list_volume_covers_for_edition(db, edition_id):
                add_path(item.get("coverPath"))
    else:
        add_path(edition.get("coverPath"))
        for item in library_deletion.list_files_for_edition(db, edition_id):
            add_path(item.get("path"))
        for item in library_deletion.list_volume_covers_for_edition(db, edition_id):
            add_path(item.get("coverPath"))
    return list(dict.fromkeys(paths))


def _path_tree(paths: list[str], root_label: str) -> dict[str, Any]:
    root = {"name": root_label, "path": root_label, "type": "folder", "children": [], "fileCount": 0, "sizeBytes": 0}
    children_by_path: dict[str, dict[str, Any]] = {root_label: root}
    for raw_path in sorted({path for path in paths if path}):
        parts = [part for part in Path(raw_path).parts if part not in {"/", ""}]
        current = root
        current_path = root_label
        for index, part in enumerate(parts):
            current_path = f"{current_path}/{part}"
            node = children_by_path.get(current_path)
            if not node:
                node = {"name": part, "path": current_path, "type": "file" if index == len(parts) - 1 else "folder", "children": [], "fileCount": 0, "sizeBytes": 0}
                children_by_path[current_path] = node
                current["children"].append(node)
            current = node
            current["fileCount"] = int(current.get("fileCount") or 0) + (1 if index == len(parts) - 1 else 0)
    return root


def _source_folder_preview(root_path: str) -> dict[str, Any]:
    path = Path(root_path)
    readable = path.exists() and path.is_dir() and os.access(path, os.R_OK)
    writable = path.exists() and path.is_dir() and os.access(path, os.W_OK)
    children: list[dict[str, Any]] = []
    if readable:
        try:
            for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:80]:
                try:
                    stat = child.stat()
                    children.append({"name": child.name, "path": str(child), "type": "folder" if child.is_dir() else "file", "sizeBytes": 0 if child.is_dir() else stat.st_size, "mtimeMs": int(stat.st_mtime * 1000)})
                except OSError:
                    children.append({"name": child.name, "path": str(child), "type": "unknown", "sizeBytes": 0, "error": "无法读取"})
        except OSError:
            readable = False
    return {"readable": readable, "writable": writable, "children": children}


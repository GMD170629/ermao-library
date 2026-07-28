"""Filesystem adapter for monitor-folder import discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.modules.imports.application.file_types import is_supported_import_filename
from app.services.audio_metadata import (
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import (
    ImportPreferences,
    SUPPORTED_IMPORT_EXTENSIONS,
    matches_ignore_patterns,
)


@dataclass(frozen=True)
class MonitorFolderConfig:
    id: str
    root_path: str
    shelf_id: str | None = None
    ignore_hidden: bool = True
    ignore_patterns: str | None = None
    min_file_size_bytes: int = 10240
    global_ignore_patterns: str = ""
    allowed_extensions: tuple[str, ...] = SUPPORTED_IMPORT_EXTENSIONS
    stability_check_enabled: bool = True
    stability_check_seconds: float = 2.0
    auto_convert_to_epub: bool = True


class ImportQueueProtocol(Protocol):
    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None: ...


@dataclass
class ScanSummary:
    directories_scanned: int = 0
    files_scanned: int = 0
    candidates_found: int = 0
    cached_files: int = 0
    ignored_files: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


def monitor_folder_config(
    row: Any,
    *,
    preferences: ImportPreferences | None = None,
) -> MonitorFolderConfig:
    preferences = preferences or ImportPreferences()
    raw_min_file_size = row.get("minFileSizeBytes")
    return MonitorFolderConfig(
        id=str(row["id"]),
        root_path=str(row["rootPath"]),
        shelf_id=str(row.get("shelfId")) if row.get("shelfId") else None,
        ignore_hidden=bool(row.get("ignoreHidden", True)),
        ignore_patterns=row.get("ignorePatterns"),
        min_file_size_bytes=int(
            10240 if raw_min_file_size is None else raw_min_file_size
        ),
        global_ignore_patterns=preferences.ignore_patterns,
        allowed_extensions=preferences.allowed_extensions,
        stability_check_enabled=preferences.stability_check_enabled,
        stability_check_seconds=preferences.stability_check_seconds,
        auto_convert_to_epub=preferences.auto_convert_to_epub,
    )


def should_ignore_path(path: Path, folder: MonitorFolderConfig) -> bool:
    if any(
        part.endswith(".part") or part.startswith(".upload-")
        for part in path.parts
    ):
        return True
    if folder.ignore_hidden and any(
        part.startswith(".") and len(part) > 1 for part in path.parts
    ):
        return True
    return matches_ignore_patterns(
        path,
        folder.global_ignore_patterns,
    ) or matches_ignore_patterns(path, folder.ignore_patterns)


def should_ignore_file(path: Path, folder: MonitorFolderConfig) -> bool:
    if should_ignore_path(path, folder):
        return True
    if not (
        is_supported_import_filename(path)
        or path.is_dir() and bool(collect_audio_bundle_files(path))
    ):
        return True
    if path.suffix and path.suffix.lower() not in folder.allowed_extensions:
        return True
    return False


_TRACK_FILE_PATTERN = re.compile(
    r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:(?:track|chapter|chap|ch|第)\s*)?[\[(]?\d{1,6}[\])]?(?:\s*[章回集节])?(?:[ ._-]+|$)",
    re.IGNORECASE,
)
_EPISODE_FILE_PATTERN = re.compile(
    r"第\s*\d{1,6}\s*[章回集节]",
    re.IGNORECASE,
)


def is_proven_audio_bundle_directory(
    path: Path,
    files: list[Path] | None = None,
) -> bool:
    try:
        candidates = (
            files if files is not None else collect_audio_bundle_files(path)
        )
    except (OSError, ValueError):
        return False
    if len(candidates) < 2:
        return False
    try:
        has_sibling_book = any(
            child.is_file()
            and not is_supported_audio_file(child)
            and is_supported_import_filename(child)
            for child in path.iterdir()
        )
    except OSError:
        return False
    if not has_sibling_book:
        return True
    return all(
        _TRACK_FILE_PATTERN.match(item.name)
        or _EPISODE_FILE_PATTERN.search(item.stem)
        for item in candidates
    )


def scan_directory_for_imports(
    root_path: Path,
    folder: MonitorFolderConfig,
    import_queue: ImportQueueProtocol,
    *,
    summary: ScanSummary | None = None,
    known_paths: set[Path] | None = None,
) -> ScanSummary:
    summary = summary or ScanSummary()
    monitor_root = Path(folder.root_path).expanduser().resolve()
    summary.directories_scanned += 1
    try:
        bundle_files = collect_audio_bundle_files(root_path)
    except ValueError as exc:
        summary.errors.append({"path": str(root_path), "error": str(exc)})
        return summary
    is_bundle = (
        bool(bundle_files)
        and root_path.resolve() != monitor_root
        and is_proven_audio_bundle_directory(root_path, bundle_files)
    )
    handled_bundle_files: set[Path] = set()
    if is_bundle:
        summary.files_scanned += len(bundle_files)
        resolved_root = root_path.resolve()
        handled_bundle_files = {item.resolve() for item in bundle_files}
        if should_ignore_path(root_path, folder):
            summary.ignored_files += len(bundle_files)
        elif (
            known_paths is not None
            and resolved_root in known_paths
            and handled_bundle_files.issubset(known_paths)
        ):
            summary.cached_files += len(bundle_files)
        else:
            summary.candidates_found += 1
            import_queue.enqueue(root_path, folder)
    try:
        entries = list(root_path.iterdir())
    except OSError as exc:
        summary.errors.append({"path": str(root_path), "error": str(exc)})
        return summary
    for entry in entries:
        try:
            if entry.is_dir():
                if is_bundle and any(
                    entry.resolve() in item.parents
                    for item in handled_bundle_files
                ):
                    continue
                if not should_ignore_path(entry, folder):
                    scan_directory_for_imports(
                        entry,
                        folder,
                        import_queue,
                        summary=summary,
                        known_paths=known_paths,
                    )
                continue
            if not entry.is_file():
                continue
            if entry.resolve() in handled_bundle_files:
                continue
            summary.files_scanned += 1
            if should_ignore_file(entry, folder):
                summary.ignored_files += 1
                continue
            if known_paths is not None and entry.resolve() in known_paths:
                summary.cached_files += 1
                continue
            summary.candidates_found += 1
            import_queue.enqueue(entry, folder)
        except OSError as exc:
            summary.errors.append({"path": str(entry), "error": str(exc)})
    return summary

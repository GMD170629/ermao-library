"""Filesystem adapter for monitor-folder import discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from app.modules.imports.application.audio_types import (
    audio_bundle_membership_is_proven,
    audio_episode_number,
)
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.application.file_types import is_supported_import_filename
from app.services.audio_metadata import (
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import (
    DEFAULT_STABILITY_CHECK_ENABLED,
    SUPPORTED_IMPORT_EXTENSIONS,
    ImportPreferences,
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
    stability_check_enabled: bool = DEFAULT_STABILITY_CHECK_ENABLED
    stability_check_seconds: float = 2.0
    auto_convert_to_epub: bool = True


class ImportQueueProtocol(Protocol):
    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None: ...


ImportIgnoreReason = Literal[
    "temporary_upload",
    "hidden_path",
    "global_ignore_pattern",
    "monitor_folder_ignore_pattern",
    "unsupported_file_type",
    "extension_not_allowed",
    "below_minimum_size",
    "audio_track_limit_exceeded",
]


@dataclass(frozen=True)
class IgnoredImportSource:
    path: Path
    reason: ImportIgnoreReason
    file_count: int = 1


@dataclass
class ScanSummary:
    directories_scanned: int = 0
    files_scanned: int = 0
    candidates_found: int = 0
    cached_files: int = 0
    ignored_files: int = 0
    ignored_sources: list[IgnoredImportSource] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)


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


def path_ignore_reason(
    path: Path,
    folder: MonitorFolderConfig,
) -> ImportIgnoreReason | None:
    if any(
        part.endswith(".part") or part.startswith(".upload-") for part in path.parts
    ):
        return "temporary_upload"
    if folder.ignore_hidden and any(
        part.startswith(".") and len(part) > 1 for part in path.parts
    ):
        return "hidden_path"
    if matches_ignore_patterns(path, folder.global_ignore_patterns):
        return "global_ignore_pattern"
    if matches_ignore_patterns(path, folder.ignore_patterns):
        return "monitor_folder_ignore_pattern"
    return None


def should_ignore_path(path: Path, folder: MonitorFolderConfig) -> bool:
    return path_ignore_reason(path, folder) is not None


def import_file_ignore_reason(
    path: Path,
    folder: MonitorFolderConfig,
) -> ImportIgnoreReason | None:
    reason = path_ignore_reason(path, folder)
    if reason is not None:
        return reason
    if not (
        is_supported_import_filename(path)
        or (path.is_dir() and bool(collect_audio_bundle_files(path)))
    ):
        return "unsupported_file_type"
    if path.suffix and path.suffix.lower() not in folder.allowed_extensions:
        return "extension_not_allowed"
    return None


def should_ignore_file(path: Path, folder: MonitorFolderConfig) -> bool:
    return import_file_ignore_reason(path, folder) is not None


def import_source_meets_minimum_size(path: Path, min_file_size_bytes: int) -> bool:
    try:
        if path.is_file():
            return path.stat().st_size >= min_file_size_bytes
        files = collect_audio_bundle_files(path)
        return bool(files) and all(
            item.stat().st_size >= min_file_size_bytes for item in files
        )
    except (AudioTrackLimitExceededError, OSError, ValueError):
        return False


def should_ignore_import_source(path: Path, folder: MonitorFolderConfig) -> bool:
    return import_source_ignore_reason(path, folder) is not None


def import_source_ignore_reason(
    path: Path,
    folder: MonitorFolderConfig,
) -> ImportIgnoreReason | None:
    reason = import_file_ignore_reason(path, folder)
    if reason is not None:
        return reason
    if not import_source_meets_minimum_size(path, folder.min_file_size_bytes):
        return "below_minimum_size"
    return None


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
    *,
    folder: MonitorFolderConfig | None = None,
) -> bool:
    try:
        candidates = files if files is not None else collect_audio_bundle_files(path)
    except (AudioTrackLimitExceededError, OSError, ValueError):
        return False
    if len(candidates) < 2:
        return False
    try:
        has_sibling_book = any(
            child.is_file()
            and not is_supported_audio_file(child)
            and is_supported_import_filename(child)
            and (folder is None or not should_ignore_import_source(child, folder))
            for child in path.iterdir()
        )
    except OSError:
        return False
    return audio_bundle_membership_is_proven(
        candidates,
        has_sibling_book=has_sibling_book,
    )


def audio_track_name_proves_membership(path: Path) -> bool:
    return bool(
        _TRACK_FILE_PATTERN.match(path.name)
        or _EPISODE_FILE_PATTERN.search(path.stem)
        or audio_episode_number(path) is not None
    )


def scan_directory_for_imports(
    root_path: Path,
    folder: MonitorFolderConfig,
    import_queue: ImportQueueProtocol,
    *,
    summary: ScanSummary | None = None,
    known_paths: set[Path] | None = None,
    _suppress_audio: bool = False,
) -> ScanSummary:
    summary = summary or ScanSummary()
    summary.directories_scanned += 1
    bundle_files: list[Path] = []
    overflowed = _suppress_audio
    if not _suppress_audio:
        try:
            bundle_files = collect_audio_bundle_files(root_path)
        except AudioTrackLimitExceededError as exc:
            overflowed = True
            summary.errors.append(
                {
                    "path": str(root_path),
                    "error": str(exc),
                    "code": exc.code,
                    "limit": exc.limit,
                    "observedCount": exc.observed_count,
                }
            )
        except ValueError as exc:
            summary.errors.append({"path": str(root_path), "error": str(exc)})
            return summary
    is_bundle = bool(bundle_files) and is_proven_audio_bundle_directory(
        root_path, bundle_files, folder=folder
    )
    handled_bundle_files: set[Path] = set()
    if is_bundle:
        summary.files_scanned += len(bundle_files)
        resolved_root = root_path.resolve()
        handled_bundle_files = {item.resolve() for item in bundle_files}
        ignore_reason = import_source_ignore_reason(root_path, folder)
        if ignore_reason is not None:
            summary.ignored_files += len(bundle_files)
            summary.ignored_sources.append(
                IgnoredImportSource(
                    path=root_path,
                    reason=ignore_reason,
                    file_count=len(bundle_files),
                )
            )
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
        entries = root_path.iterdir()
    except OSError as exc:
        summary.errors.append({"path": str(root_path), "error": str(exc)})
        return summary
    for entry in entries:
        try:
            if entry.is_dir():
                if is_bundle and any(
                    entry.resolve() in item.parents for item in handled_bundle_files
                ):
                    continue
                if not should_ignore_path(entry, folder):
                    scan_directory_for_imports(
                        entry,
                        folder,
                        import_queue,
                        summary=summary,
                        known_paths=known_paths,
                        _suppress_audio=overflowed,
                    )
                continue
            if not entry.is_file():
                continue
            if overflowed and is_supported_audio_file(entry):
                summary.files_scanned += 1
                summary.ignored_files += 1
                continue
            if entry.resolve() in handled_bundle_files:
                continue
            summary.files_scanned += 1
            ignore_reason = import_source_ignore_reason(entry, folder)
            if ignore_reason is not None:
                summary.ignored_files += 1
                summary.ignored_sources.append(
                    IgnoredImportSource(path=entry, reason=ignore_reason)
                )
                continue
            if known_paths is not None and entry.resolve() in known_paths:
                summary.cached_files += 1
                continue
            summary.candidates_found += 1
            import_queue.enqueue(entry, folder)
        except OSError as exc:
            summary.errors.append({"path": str(entry), "error": str(exc)})
    return summary
